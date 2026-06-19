"""Petasos content security plugin for Hermes Agent.

Wires the Petasos pipeline and ToolCallGuard into Hermes via the plugin
hook system. All tool calls pass through pre_tool_call enforcement;
audit and alert events route to Hermes's standard logger.

Deploy: copy this directory to the active Hermes profile's plugin dir:
        v0.16+  profiles/<active>/plugins/petasos/
        v0.15   ~/.hermes/plugins/petasos/  (macOS)
                %LOCALAPPDATA%\\hermes\\plugins\\petasos\\  (Windows)
Config: add a top-level ``petasos:`` section to the profile's config.yaml
Env:    PETASOS_LICENSE_KEY, PETASOS_SESSION_SECRET, PETASOS_HASH_KEY
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from petasos._types import Severity  # PET-112: dep-light (enum + dataclasses, no ML imports)
from petasos.normalize import canonicalize_tool_name  # PET-118: dep-light (re + unicodedata)
from petasos.session.formatting import (  # PET-77: dep-light (string formatting over dataclasses)
    format_block_message,
    format_content_block,
)

if TYPE_CHECKING:
    from petasos import PetasosConfig
    from petasos.console._paths import HermesConfigResolution

logger = logging.getLogger("petasos.plugin")

# ---------------------------------------------------------------------------
# Module state — lazy-initialized on first hook invocation
# ---------------------------------------------------------------------------

_pipeline = None
_guard = None
_config: dict[str, Any] | None = None
_init_lock = threading.Lock()
_initialized = False
_init_error: str | None = None
_session_ids: dict[int, str] = {}

# PET-130: the gateway's session-bound config resolution, captured once at the top
# of register() from the operator-trusted boot environment and pinned for the
# process lifetime. _is_armed() and _maybe_reconfigure() pass it to the armed/reload
# readers so a profile session never re-resolves to the global config mid-session.
# None means capture has not run (or failed) -> the readers fall back to an ambient
# per-call resolve. Never re-derived from in-session-mutable state (PET-125).
_session_resolution: HermesConfigResolution | None = None


def _reset_session_resolution() -> None:
    """Test seam — drop the pinned resolution (mirrors _reset_disarm_log)."""
    global _session_resolution
    _session_resolution = None


# PET-111: live arm/disarm. _pre_tool_call/_post_tool_call re-read petasos.enabled
# per call (mtime+size+TTL-cached in petasos.console._armed) rather than latching
# it at init, so an operator's Equipped/Unequipped toggle affects running sessions.
# The disarm tripwire is rate-limited so a bypass of (even tier-3) enforcement is
# always attributable in the log.
_disarm_log_lock = threading.Lock()
_last_disarm_log = 0.0
_DISARM_LOG_EVERY_S = 30.0

# PET-138: per-session count of tool calls bypassed while disarmed. Bumped on
# EVERY disarmed _pre_tool_call (independent of the rate-limited heartbeat above),
# so the operator sees an authoritative count, not a 30s sample. The cumulative
# per-session total rides the rate-limited bypassed_disarmed heartbeat as
# `bypassed_count`. _bypass_lock guards BOTH _bypass_counts AND the _session_ids
# insert in _derive_session_id (which now runs on the disarm hot path, not once
# per 30s). It is a non-reentrant Lock: _derive_session_id and _bump_bypass_count
# each acquire and release it independently (sequential, never nested) — do not
# wrap the whole disarm block in it. _MAX_DISARM_SESSIONS bounds the map
# drop-oldest, mirroring server._MAX_TALLY_SESSIONS (an independent bound by
# design; the plugin cannot import server without pulling aiohttp onto the hot
# path).
_bypass_lock = threading.Lock()
_bypass_counts: dict[str, int] = {}
_MAX_DISARM_SESSIONS = 10_000

# PET-126: live config reload. The cross-process re-read (petasos.console._reload)
# detects a config.yaml change on the hot path and _maybe_reconfigure applies it
# to the running pipeline + guard + lineage registry. Two rate-limited streams
# reuse the _DISARM_LOG_EVERY_S window but keep their OWN clocks so neither can
# suppress the other (or the security-critical PETASOS_DISARMED tripwire): an
# attribution WARNING on each applied change, and a failure WARNING on a
# build/apply error (keep-last-good).
_reload_log_lock = threading.Lock()
_last_attribution_log = 0.0
_last_reload_fail_log = 0.0

# PET-132: live profile-swap re-bind. PET-130 pins _session_resolution once at boot;
# these make the pin RE-establishable on an operator-trusted profile change without a
# process restart. _rebind_to_profile re-captures the resolution from the TRUSTED profile
# home (never the agent-writable active_profile pointer, PET-125 / Decision 2), resets the
# (mtime,size)-keyed armed/reload caches (Decision 5), refreshes _config, and hot-applies
# the pipeline config via PET-126's _apply_reconfigure (Decision 4). The whole worker runs
# under _rebind_lock so concurrent re-binds commit in re-pin order (Decision 7). The two
# process-global flags keep a re-runnable register() (the forced-rediscovery route) from
# double-registering hooks or spawning a second init thread (Decision 3). _last_rebind_log
# is a DEDICATED clock — never the disarm/reload clocks — so a routine reload failure
# cannot suppress a one-shot operator-triggered re-bind line (Decision 6).
_rebind_lock = threading.Lock()
_hooks_registered = False
_init_thread_started = False
_rebind_log_lock = threading.Lock()
_last_rebind_log = 0.0


def _reset_hooks_registered() -> None:
    """Test seam — clear the one-shot hook-registration flag (Decision 3)."""
    global _hooks_registered
    _hooks_registered = False


def _reset_init_thread_started() -> None:
    """Test seam — clear the one-shot init-thread-spawn flag (Decision 3)."""
    global _init_thread_started
    _init_thread_started = False


def _reset_rebind_log() -> None:
    """Test seam — reset the dedicated re-bind rate-limit clock (Decision 6)."""
    global _last_rebind_log
    with _rebind_log_lock:
        _last_rebind_log = 0.0


# PET-107: sub-agent lineage (Option A). The registry is constructed in
# _deferred_init (it shares the tracker's clock + lock discipline), but the
# subagent_start/subagent_stop hooks are registered earlier in register(). The
# handlers therefore reference the registry lazily through this module global —
# a hook firing before init completes (registry None) is a safe no-op.
_lineage_registry = None
# True iff BOTH subagent hooks registered. A is wired only when both are present
# (an edge store created but never dropped-on-stop would leak edges); otherwise
# A degrades fully to C (lineage=None). Set in register(), read in _deferred_init.
_subagent_hooks_available = False

# Dedicated event loop for async Petasos calls (evaluate is async,
# but Hermes invoke_hook is sync).
_async_loop: asyncio.AbstractEventLoop | None = None
_async_thread: threading.Thread | None = None

READ_ONLY_TOOLS = frozenset(
    {
        "read_file",
        "search",
        "list_directory",
        "session_search",
        "web_search",
        "web_extract",
        "vision_analyze",
        "mcp_vigil_harbor_memory_search",
        "mcp_vigil_harbor_memory_fetch",
        "mcp_vigil_harbor_memory_list",
        "mcp_vigil_harbor_memory_query",
        "mcp_vigil_harbor_memory_sources",
        "mcp_vigil_harbor_memory_status",
        "mcp_plane_list_work_items",
        "mcp_plane_retrieve_work_item",
        "mcp_plane_retrieve_work_item_by_identifier",
        "mcp_plane_list_projects",
    }
)

# PET-118: derived sibling canonical set. READ_ONLY_TOOLS stays the immutable raw
# source-of-truth; _READ_ONLY_CANON is canonicalized at MODULE LOAD (not _deferred_init)
# because _is_dangerous runs in _fallback_pre_tool_call during the init window, before
# _deferred_init completes. The same `if c` empty-drop the egress init uses applies here:
# a name that canonicalizes away (a future homoglyph-only / prefix-only constant) never
# enters the set, so _is_dangerous("") stays True (fail-secure) unconditionally — no
# `assert`, which `python -O` / PYTHONOPTIMIZE would strip. Every current entry is plain
# ASCII and canonicalizes non-empty, so the filter is a no-op today, a regression guard
# tomorrow.
_READ_ONLY_CANON = frozenset(c for c in (canonicalize_tool_name(t) for t in READ_ONLY_TOOLS) if c)


def _is_dangerous(tool_name: str) -> bool:
    return canonicalize_tool_name(tool_name) not in _READ_ONLY_CANON


# ---------------------------------------------------------------------------
# PET-112: ordinal severity gate + egress-sink classification
# ---------------------------------------------------------------------------

# Lower rank = worse — the established convention (four existing copies in
# pipeline.py / presidio.py / alerting.py / formatting.py). A fifth copy in this
# deployment artifact is preferable to importing a private name across the
# package -> docs/deployment/ boundary.
_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}
_BLOCK_RANK = _SEVERITY_RANK[Severity.HIGH]  # block at HIGH or worse (rank <= 1)


def _blocks(severity: Severity) -> bool:
    """Ordinal severity gate (replaces the broken lexicographic compare, PET-112 D-CAVEAT).

    Unknown severities sort to 999 -> do not block, matching the _SEVERITY_RANK.get(..., 999)
    idiom used across the package.
    """
    return _SEVERITY_RANK.get(severity, 999) <= _BLOCK_RANK


def _worst(findings):
    """Severity-first, confidence-tiebreak selection (PET-51 ordering).

    Caller guarantees a non-empty sequence (only ever called inside an `if list:` guard),
    so min() never raises on empty input.
    """
    return min(findings, key=lambda f: (_SEVERITY_RANK.get(f.severity, 999), -f.confidence))


# Resolved in _deferred_init from config.egress_sink_tools, canonicalized once at init
# (PET-118); canonical membership mirrors _is_dangerous. Written once under _init_lock
# before _initialized flips; read lock-free in _pre_tool_call (which only runs post-init).
# Atomic name rebind — no torn read under the GIL.
_egress_sink_tools: frozenset[str] = frozenset()


def _is_egress_sink(tool_name: str) -> bool:
    return canonicalize_tool_name(tool_name) in _egress_sink_tools


# ---------------------------------------------------------------------------
# PET-134: per-namespace source-taint egress fence
# ---------------------------------------------------------------------------

# The taint store (per-session bounded span set) and the canonicalized source-namespace
# prefix set, built in _deferred_init from config beside _egress_sink_tools and rebuilt in
# _apply_reconfigure. Written once under _init_lock before _initialized flips; read lock-free
# in the post-init hot path (_pre_tool_call / _post_tool_call). Both default to the
# feature-off sentinels (None store, empty set) so the fence is a no-op until an operator
# declares a source namespace. _taint_store is typed loosely (Any) to keep this deployment
# artifact import-light — the concrete type is petasos.session.taint.SessionTaintStore.
_taint_store: Any = None
_source_taint_namespaces: frozenset[str] = frozenset()


def _match_source_namespace(tool_name: str) -> str | None:
    """Return the declared source-namespace prefix the producing ``tool_name`` falls under,
    or ``None``. Canonicalizes the tool name through the SAME primitive as the sinks
    (PET-118: closes the variant bypass on the source side) and PREFIX-matches it (a source
    namespace labels a FAMILY of tools, unlike the exact membership a sink uses). The
    LONGEST matching prefix wins, so overlapping declarations (``mcp_`` and ``mcp_bank_``)
    resolve deterministically to the most specific provenance (D-NS)."""
    canon_tool = canonicalize_tool_name(tool_name)
    return max(
        (p for p in _source_taint_namespaces if canon_tool.startswith(p)),
        key=len,
        default=None,
    )


# ---------------------------------------------------------------------------
# Async bridge — dedicated event loop in a background thread
# ---------------------------------------------------------------------------


def _start_async_loop() -> None:
    global _async_loop
    _async_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_async_loop)
    _async_loop.run_forever()


def _ensure_async_loop() -> None:
    global _async_thread
    if _async_thread is None or not _async_thread.is_alive():
        _async_thread = threading.Thread(
            target=_start_async_loop,
            daemon=True,
            name="petasos-async",
        )
        _async_thread.start()
        while _async_loop is None:
            threading.Event().wait(0.01)


def _run_async(coro):
    _ensure_async_loop()
    future = asyncio.run_coroutine_threadsafe(coro, _async_loop)
    return future.result(timeout=15)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def _load_config(res: HermesConfigResolution | None = None) -> dict[str, Any]:
    """Read petasos: section from the resolved Hermes config.yaml.

    PET-130: ``res`` is the boot-captured resolution; when supplied, boot resolves
    exactly once (the same file the armed/reload reads are pinned to). When ``None``,
    resolve from environment as before.
    """
    from petasos.console._paths import read_petasos_section, resolve_hermes_config_path

    res = res if res is not None else resolve_hermes_config_path()
    logger.info("loading config from %s [tier=%s]", res.path, res.tier)
    if res.warning:
        logger.warning("Hermes profile resolution: %s", res.warning)
    if not res.path.is_file():
        logger.warning("Hermes config not found at %s — using Petasos defaults", res.path)
        return {}
    section = read_petasos_section(res)
    if not section:
        logger.warning(
            "No 'petasos:' section in config.yaml — Petasos running with "
            "defaults (all features disabled). Add a petasos: section to "
            "enable enforcement."
        )
    return section


def _build_config_from_section(section: dict[str, Any]) -> PetasosConfig:
    """Build a validated PetasosConfig from a raw petasos: section.

    Applies the SAME env overlay as boot (PET-126 Decision 10): injects
    session_secret / hash_key from the environment and applies boot's
    hash_key-missing anonymize=False defang, so a boot config and a live-reload
    config are equivalent. Operates on a copy and never mutates the caller's dict.
    Raises (TypeError/ValueError) on a validation failure of any other field; the
    reload path absorbs that via its fail-safe keep-last-good branch.
    """
    from petasos import PetasosConfig

    raw = dict(section)
    # host_id is a Pipeline constructor arg (not a config field) and `enabled` is
    # owned by the _armed fast path; neither is reconfigured (Decision 2).
    raw.pop("host_id", None)
    raw.pop("enabled", None)

    session_secret_b64 = os.environ.get("PETASOS_SESSION_SECRET")
    if session_secret_b64:
        # Invalid base64: leave as-is (boot warns separately and does not inject).
        with contextlib.suppress(Exception):
            raw["session_secret"] = base64.b64decode(session_secret_b64)

    hash_key = os.environ.get("PETASOS_HASH_KEY")
    if hash_key:
        raw["hash_key"] = hash_key
    elif raw.get("redaction_mode") == "hash":
        # Boot's defang: downgrade rather than raise when hash_key is absent.
        raw["anonymize"] = False

    return PetasosConfig.from_dict(raw)


# ---------------------------------------------------------------------------
# Deferred initialization — runs in background thread from register()
# ---------------------------------------------------------------------------


def _deferred_init() -> None:
    global _pipeline, _guard, _initialized, _init_error

    with _init_lock:
        if _initialized or _init_error:
            return

        try:
            from petasos import PetasosConfig, Pipeline, ToolCallGuard
            from petasos.scanners import MinimalScanner

            raw_config = _config or {}

            host_id = raw_config.pop("host_id", "hermes-gavin-01")
            # PET-111 (Option A): build the pipeline regardless of the boot-time
            # `enabled` value; enforcement is gated per-call by _is_armed() so a
            # re-arm mid-session pays no cold-start penalty. The "disabled"
            # _init_error sentinel is retired — _init_error now latches only a
            # genuine init exception.
            enabled = raw_config.pop("enabled", True)
            logger.info(
                "Petasos starting %s (petasos.enabled=%s)",
                "armed" if enabled else "disarmed",
                enabled,
            )

            # Boot-time operator guidance. The actual env overlay + validation is
            # the shared _build_config_from_section (also used by the live reload,
            # PET-126 Decision 10), so a boot config and a live-reload config are
            # equivalent. The warnings stay here so the reload path does not re-emit
            # them on every applied change.
            session_secret_b64 = os.environ.get("PETASOS_SESSION_SECRET")
            if session_secret_b64:
                try:
                    base64.b64decode(session_secret_b64)
                except Exception:
                    logger.warning(
                        "PETASOS_SESSION_SECRET is not valid base64"
                        " — HMAC session binding disabled"
                    )
            else:
                logger.warning("PETASOS_SESSION_SECRET not set — HMAC session binding disabled")

            if (
                not os.environ.get("PETASOS_HASH_KEY")
                and raw_config.get("redaction_mode") == "hash"
            ):
                logger.warning(
                    "PETASOS_HASH_KEY not set but redaction_mode=hash "
                    "— PII anonymization will fail. Set PETASOS_HASH_KEY "
                    "or change redaction_mode."
                )

            try:
                config = _build_config_from_section(raw_config)
            except (TypeError, ValueError) as exc:
                logger.error("PetasosConfig validation failed: %s — using defaults", exc)
                config = PetasosConfig()

            scanners = [MinimalScanner()]
            unavailable: list[str] = []
            try:
                from petasos.scanners import LlmGuardScanner

                instance = LlmGuardScanner()
                scanners.append(instance)
                avail, reason, _cause = instance.availability()
                if avail:
                    logger.info("LLM Guard backend verified — scanner active")
                else:
                    unavailable.append("llm_guard")
                    logger.warning(
                        "LLM Guard backend missing — scanner registered degraded "
                        "(every scan will error): %s",
                        reason,
                    )
            except ImportError:
                unavailable.append("llm_guard")
                logger.info("LLM Guard not installed — syntactic-only for that backend")
            except Exception as exc:
                unavailable.append("llm_guard")
                logger.warning("LLM Guard failed to load: %s", exc)

            try:
                from petasos.scanners import LlamaFirewallScanner

                instance = LlamaFirewallScanner()
                scanners.append(instance)
                avail, reason, _cause = instance.availability()
                if avail:
                    logger.info("LlamaFirewall backend verified — scanner active")
                else:
                    unavailable.append("llama_firewall")
                    logger.warning(
                        "LlamaFirewall backend missing — scanner registered degraded "
                        "(every scan will error): %s",
                        reason,
                    )
            except ImportError:
                unavailable.append("llama_firewall")
                logger.info("LlamaFirewall not installed — skipped")
            except Exception as exc:
                unavailable.append("llama_firewall")
                logger.warning("LlamaFirewall failed to load: %s", exc)

            try:
                from petasos.scanners import PresidioScanner

                instance = PresidioScanner()
                scanners.append(instance)
                avail, reason, _cause = instance.availability()
                if avail:
                    logger.info("Presidio backend verified — scanner active")
                else:
                    unavailable.append("presidio")
                    logger.warning(
                        "Presidio backend missing — scanner registered degraded "
                        "(every scan will error): %s",
                        reason,
                    )
            except ImportError:
                unavailable.append("presidio")
                logger.info("Presidio not installed — PII detection unavailable")
            except Exception as exc:
                unavailable.append("presidio")
                logger.warning("Presidio failed to load: %s", exc)

            _pipeline = Pipeline(
                config=config,
                scanners=scanners,
                host_id=host_id,
                on_audit=_handle_audit,
                on_alert=_handle_alert,
            )

            license_key = os.environ.get("PETASOS_LICENSE_KEY")
            if license_key:
                from petasos import LicenseState

                state = _pipeline.activate(license_key)
                if state == LicenseState.VALID:
                    logger.info("Petasos license validated (enterprise)")
                    for feat in (
                        "frequency",
                        "escalation",
                        "tool_guard",
                        "audit",
                        "alerting",
                    ):
                        if not _pipeline.is_feature_enabled(feat):
                            logger.warning(
                                "Premium feature '%s' not available despite valid license",
                                feat,
                            )
                else:
                    logger.warning("Petasos license invalid (state=%s) — running OSS-only", state)
            else:
                logger.info(
                    "PETASOS_LICENSE_KEY not set — all features available (license is optional)"
                )

            from petasos import FrequencyTracker, LineageRegistry, SessionTaintStore

            global _lineage_registry
            if _subagent_hooks_available:
                # A + C: construct ONE registry before the tracker, wire the
                # tracker's pin/unpin callbacks to it, and hand it to the guard.
                # Hooks carry raw session_ids; the registry keys on raw ids
                # (matching is_terminated); the guard mints per-ancestor tokens
                # for get_state.
                registry = LineageRegistry(config)
                _lineage_registry = registry
                tracker = FrequencyTracker(
                    config,
                    is_pinned=registry.is_pinned,
                    on_terminate=registry.unregister,
                )
                _guard = ToolCallGuard(_pipeline, tracker, config, lineage=registry)
                logger.info("Petasos sub-agent lineage (A) + delegation fan-out gate (C) active")
            else:
                # C only: no sub-agent hooks, so lineage no-ops (no chain walk,
                # no pinning). The fan-out gate still rate-limits delegate spawns.
                tracker = FrequencyTracker(config)
                _guard = ToolCallGuard(_pipeline, tracker, config, lineage=None)
                logger.info(
                    "Petasos delegation fan-out gate (C) active; sub-agent lineage (A) "
                    "inactive (sub-agent hooks unavailable)"
                )

            # PET-112: publish the egress-sink set under the same happens-before as
            # _pipeline/_guard (written before _initialized flips; read lock-free in the
            # post-init hot path). The `global` is MANDATORY — without it the assignment
            # binds a function-local and leaves the module frozenset empty forever,
            # silently disabling egress PII blocking.
            global _egress_sink_tools
            # PET-118: canonicalize once here through the SAME shared primitive the guard
            # uses, mirroring the delegate_tool_names template (canonicalize, drop names
            # that normalize away via `if c`, warn when the resolved set is empty). A name
            # that is purely a namespace prefix (e.g. "mcp__acme__") passes config
            # validation but canonicalizes to "" — the `if c` filter drops it so the set
            # never contains "" (no false match in _is_egress_sink).
            _egress_sink_tools = frozenset(
                c for c in (canonicalize_tool_name(t) for t in config.egress_sink_tools) if c
            )
            if not _egress_sink_tools:
                logger.warning(
                    "egress_sink_tools is empty (or all names canonicalized away) — "
                    "PII will not be blocked on any egress tool"
                )

            # PET-134: build the source-taint set + store under the SAME happens-before as
            # _egress_sink_tools (written before _initialized flips; read lock-free in the
            # hot path). The `global` is MANDATORY — without it the assignments bind
            # function-locals and leave the module set frozen empty / the store None forever,
            # silently disabling the fence (the exact footgun the egress comment warns of).
            # _source_taint_namespaces uses the identical canonicalize-drop-empty-warn idiom;
            # the prefixes are canonicalized so a variant-named source tool still matches
            # (PET-118 on the source side).
            global _taint_store, _source_taint_namespaces
            _source_taint_namespaces = frozenset(
                c for c in (canonicalize_tool_name(t) for t in config.source_taint_namespaces) if c
            )
            _taint_store = SessionTaintStore(config)
            if config.source_taint_namespaces and not _source_taint_namespaces:
                logger.warning(
                    "source_taint_namespaces is set but all names canonicalized away — "
                    "the source-taint egress fence will match no producing tool"
                )

            scanner_names = [s.name for s in scanners]
            logger.info(
                "Petasos initialized: scanners=%s, unavailable=%s, fail_mode=%s, host_id=%s",
                scanner_names,
                unavailable,
                config.fail_mode,
                host_id,
            )

            _initialized = True

        except Exception as exc:
            _init_error = str(exc)
            logger.error("Petasos initialization failed: %s", exc, exc_info=True)


_fallback_scanner = None
_fallback_lock = threading.Lock()


def _get_fallback_scanner():
    global _fallback_scanner
    if _fallback_scanner is None:
        with _fallback_lock:
            if _fallback_scanner is None:
                from petasos.scanners import MinimalScanner

                _fallback_scanner = MinimalScanner()
    return _fallback_scanner


def _ensure_initialized() -> bool:
    if _initialized:
        return True
    if _init_error:
        return False
    _deferred_init()
    return _initialized


# ---------------------------------------------------------------------------
# Audit / alert callbacks
# ---------------------------------------------------------------------------


def _handle_audit(event) -> None:
    logger.info(
        "PETASOS_AUDIT session=%s seq=%s type=%s",
        event.session_id,
        event.sequence_number,
        event.event_type,
    )


def _handle_alert(alert) -> None:
    logger.warning(
        "PETASOS_ALERT rule=%s tier=%s session=%s: %s",
        alert.rule_id,
        getattr(alert, "tier", "n/a"),
        alert.session_id,
        getattr(alert, "message", ""),
    )


# ---------------------------------------------------------------------------
# Hook callbacks
# ---------------------------------------------------------------------------


def _derive_session_id(task_id: str, kwargs: dict) -> str:
    if task_id:
        return task_id
    agent = kwargs.get("_agent")
    if agent is not None:
        agent_id = id(agent)
        # PET-138: this check-then-set on the process-global _session_ids dict now
        # runs on every disarmed call (the disarm fast path), not once per 30s, so
        # it must be thread-safe on the multi-threaded gateway. Guard with
        # _bypass_lock so two threads racing a fresh _agent cannot mint two ids
        # (split count) or trigger an unsafe concurrent dict resize.
        with _bypass_lock:
            if agent_id not in _session_ids:
                _session_ids[agent_id] = f"desktop-{uuid.uuid4().hex[:12]}"
            return _session_ids[agent_id]
    return f"anon-{uuid.uuid4().hex[:8]}"


def _bump_bypass_count(session_id: str) -> int:
    """PET-138: increment the per-session disarmed-bypass counter and return the new
    total. O(1) under _bypass_lock. Drop-oldest by insertion order when the map
    exceeds _MAX_DISARM_SESSIONS (mirrors server._bump_block_tally's bound).
    """
    with _bypass_lock:
        new_count = _bypass_counts.get(session_id, 0) + 1
        _bypass_counts[session_id] = new_count
        if len(_bypass_counts) > _MAX_DISARM_SESSIONS:
            del _bypass_counts[next(iter(_bypass_counts))]
        return new_count


def _reset_bypass_counts() -> None:
    """Test seam — clear the per-session disarmed-bypass counters (mirrors
    _reset_disarm_log). Also clears _session_ids so a concurrency test can assert
    a clean mint."""
    global _session_ids
    with _bypass_lock:
        _bypass_counts.clear()
        _session_ids = {}


def _fallback_pre_tool_call(
    tool_name: str, args: dict, task_id: str, **kwargs
) -> dict[str, str] | None:
    """Syntactic-only guard during init window. Scans tool params through
    MinimalScanner. Blocks if injection patterns found in dangerous tools."""
    if not _is_dangerous(tool_name):
        return None
    try:
        import json

        scanner = _get_fallback_scanner()
        param_text = json.dumps(args, default=str)[:100_000]
        result = _run_async(scanner.scan(param_text, direction="inbound"))
        if result.findings:
            # PET-112: ordinal gate (a lone CRITICAL now blocks; MEDIUM/LOW no longer do).
            # MinimalScanner emits no PII findings (syntactic only), so no egress logic here.
            worst = _worst(result.findings)
            if _blocks(worst.severity):
                logger.warning(
                    "PETASOS_FALLBACK_BLOCK tool=%s — init in progress, syntactic scan found: %s",
                    tool_name,
                    worst.rule_id,
                )
                # PET-131: a cold-start (init-window) block is still a gateway block the
                # operator must see — emit it beside the log line like the main path.
                _emit_enforcement_event(
                    session_id=_derive_session_id(task_id, kwargs),
                    tool=tool_name,
                    event_type="quarantine",
                    severity=worst.severity.name,
                    rule_id=worst.rule_id,
                    reason=worst.message,
                )
                return {
                    "action": "block",
                    # PET-77: route through the library formatter (contract: [BLOCKED by Petasos]
                    # prefix, tool name, NOT executed, top-finding clause).
                    "message": format_content_block("init", tool_name, result.findings),
                }
    except Exception as exc:
        logger.debug("Fallback scan failed: %s — allowing", exc)
    return None


def _is_armed() -> bool:
    """PET-111: True unless the operator set petasos.enabled=false. Fail-secure True.

    PET-130: reads through the session-bound resolution captured at boot so a
    profile session honors a disarm written to its own config rather than re-reading
    the global. ``_session_resolution`` is None until register() captures it, in which
    case read_armed falls back to an ambient per-call resolve.
    """
    try:
        from petasos.console._armed import read_armed

        return read_armed(_session_resolution)
    except Exception:
        return True  # never fail open into disarmed


def _reset_disarm_log() -> None:
    """Test seam — reset the disarm tripwire rate-limit clock."""
    global _last_disarm_log
    with _disarm_log_lock:
        _last_disarm_log = 0.0


def _log_disarmed_bypass(tool_name: str) -> bool:
    """Rate-limited WARNING so an operator-disarmed bypass is always attributable.

    PET-131: returns ``True`` iff it actually logged this call (the rate-limit
    window opened), so the caller can emit a 1:1 enforcement event onto the same
    clock — the surfaced "bypassed (disarmed)" row and the ``PETASOS_DISARMED`` log
    line then share one source of truth and one ``_DISARM_LOG_EVERY_S`` cadence.
    """
    global _last_disarm_log
    now = time.monotonic()
    with _disarm_log_lock:
        if now - _last_disarm_log < _DISARM_LOG_EVERY_S:
            return False
        _last_disarm_log = now
    logger.warning(
        "PETASOS_DISARMED tool=%s — enforcement bypassed by operator (Unequipped)",
        tool_name,
    )
    return True


def _emit_enforcement_event(
    *,
    session_id: str,
    tool: str,
    event_type: str,
    tier: str | None = None,
    rule_id: str | None = None,
    severity: str | None = None,
    reason: str = "",
    param_scan_degraded: bool = False,
    armed: bool = True,
    bypassed_count: int | None = None,
) -> None:
    """PET-131: emit a structured enforcement event onto the cross-process spool the
    dashboard drains, beside the existing decision-point log line (one emit per log
    line — log and surface share one source of truth, spec D1/D4).

    PET-138: ``bypassed_count`` carries the cumulative per-session count of
    disarmed bypasses on the rate-limited ``bypassed_disarmed`` heartbeat so the
    dashboard can surface an authoritative count, not a 30s sample. None for all
    other event types.

    Self-guarded and fail-open (spec D5): surfacing a block must never gate, delay,
    or break the tool call, so the whole body is wrapped and swallows everything.
    The write itself is an O(1) local append (``petasos.console._events``), the same
    hot-path cost class as the per-call ``read_armed`` file read — not a network
    call and not a blocking ``await`` on the decision path.
    """
    try:
        from petasos.console._events import emit_enforcement_event

        emit_enforcement_event(
            {
                "session_id": session_id,
                "tool": tool,
                "event_type": event_type,
                "tier": tier,
                "rule_id": rule_id,
                "severity": severity,
                "reason": reason,
                "param_scan_degraded": param_scan_degraded,
                "direction": "tool_call",
                "armed": armed,
                "bypassed_count": bypassed_count,
            }
        )
    except Exception:
        pass


def _reset_reload_logs() -> None:
    """Test seam — reset the PET-126 reload rate-limit clocks."""
    global _last_attribution_log, _last_reload_fail_log
    with _reload_log_lock:
        _last_attribution_log = 0.0
        _last_reload_fail_log = 0.0


def _log_reconfigure_applied() -> None:
    """Rate-limited WARNING so every applied live config change is attributable."""
    global _last_attribution_log
    now = time.monotonic()
    with _reload_log_lock:
        if now - _last_attribution_log < _DISARM_LOG_EVERY_S:
            return
        _last_attribution_log = now
    logger.warning("PETASOS_RECONFIGURED: live config.yaml change applied to the running session")


def _log_reload_failure(detail: str) -> None:
    """Rate-limited WARNING for a build/apply failure; the live config is unchanged.

    Its own clock (never _last_disarm_log / _last_attribution_log) so a
    persistently-malformed section, which re-detects every TTL, cannot spam the
    log or suppress the disarm tripwire.
    """
    global _last_reload_fail_log
    now = time.monotonic()
    with _reload_log_lock:
        if now - _last_reload_fail_log < _DISARM_LOG_EVERY_S:
            return
        _last_reload_fail_log = now
    logger.warning("PETASOS_RELOAD_FAILED: %s; keeping last-good config", detail)


async def _apply_reconfigure(cfg: PetasosConfig) -> None:
    """Apply a reloaded config to the live gateway as one uninterrupted unit.

    Dispatched onto _async_loop via _run_async (PET-126 Decision 6), so it is
    serialized with scans between await points. The body is fully synchronous (it
    never yields), so the steps are atomic with respect to any other loop task.

    Two-phase (Decision 5): validate everything that can fail BEFORE committing
    anything, then commit. Because guard.validate_config and the apply tracker
    stages parse the SAME already-validated cfg through pure functions, phase-1
    success guarantees no commit step raises, so there is no partial cross-object
    apply. The gateway owns the guard, lineage registry, and egress set, which the
    pipeline cannot reach, so all four are reconfigured here (Decision 4).
    """
    # Phase 1: validate (no mutation) — D8 overlap + frequency_weights trial.
    _guard.validate_config(cfg)
    # Phase 2: commit.
    _pipeline.reconfigure(cfg)
    _guard.apply_config(cfg)
    if _lineage_registry is not None:
        _lineage_registry.apply_config(cfg)
    global _egress_sink_tools, _source_taint_namespaces
    _egress_sink_tools = frozenset(
        c for c in (canonicalize_tool_name(t) for t in cfg.egress_sink_tools) if c
    )
    # PET-134: rebuild the source-namespace set and apply the live FP floor beside the
    # egress rebuild (the gateway owns this state; the pipeline cannot reach it). The
    # `global` is mandatory for the rebind (the store itself is mutated in place, not
    # reassigned). apply_config only rebinds an already-validated scalar under the store
    # lock, so it cannot raise on this phase-1-validated cfg (commit-phase no-raise).
    _source_taint_namespaces = frozenset(
        c for c in (canonicalize_tool_name(t) for t in cfg.source_taint_namespaces) if c
    )
    if _taint_store is not None:
        _taint_store.apply_config(cfg)


def _maybe_reconfigure() -> None:
    """PET-126: detect a config.yaml change and hot-apply it to the live session.

    Called at the top of _pre_tool_call once initialized. The no-change path is
    one os.stat (see _reload). On a detected change: build the config (failure ->
    rate-limited fail log, keep last-good, do NOT commit so it retries next call)
    and dispatch _apply_reconfigure onto _async_loop. On a successful apply:
    commit_seen(key) + a rate-limited attribution WARNING. On apply failure:
    swallow fail-safe (matching the _is_armed / guard-eval posture, rate-limited
    fail log) and do NOT commit, so the change is re-attempted next call. A reload
    error never blocks a tool call and never silently pins a stale config.
    """
    try:
        from petasos.console._reload import commit_seen, read_changed_section
    except Exception:
        return

    # PET-130: peek and commit MUST share the same session-bound resolution so the
    # committed key and section describe one file.
    changed = read_changed_section(_session_resolution)
    if changed is None:
        return
    section, key = changed
    try:
        cfg = _build_config_from_section(section)
    except Exception as exc:
        _log_reload_failure(f"build failed: {exc}")
        return  # keep last-good; not committed -> retried next call
    try:
        _run_async(_apply_reconfigure(cfg))
    except Exception as exc:
        _log_reload_failure(f"apply failed: {exc}")
        return  # keep last-good; not committed -> retried next call
    commit_seen(key, _session_resolution)
    _log_reconfigure_applied()


# ---------------------------------------------------------------------------
# PET-132: trusted profile-swap re-bind (re-establish the boot-pin on a profile change)
# ---------------------------------------------------------------------------


def _validated_profile_home(profile_home: Any) -> tuple[Path | None, str]:
    """Validate a trusted profile-change payload (Decision 2/6 fail-secure floor).

    Returns ``(home, "")`` on success or ``(None, reason)`` on rejection. The payload
    must be a non-empty, ABSOLUTE path that resolves to an existing directory. The
    absolute check runs BEFORE ``resolve()`` so a relative path can never be anchored to
    the process CWD — closing the CWD vector the brief's D-WIN names (an agent that can
    chdir cannot make a relative home resolve into a tree it controls). ``resolve(strict=
    False)`` normalizes a well-formed absolute path (``..`` segments) without requiring
    every component to pre-exist; the ``is_dir()`` check is the existence gate.
    """
    if not profile_home:
        return None, "empty profile_home"
    if not isinstance(profile_home, (str, os.PathLike)):
        return None, f"non-path profile_home type={type(profile_home).__name__}"
    candidate = Path(profile_home)
    # Absolute BEFORE resolve(): resolve() would anchor a relative path to CWD and mask
    # the rejection. On Windows is_absolute() requires a drive or UNC root, so a bare or
    # mixed-separator relative path is rejected here (tested on win32).
    if not candidate.is_absolute():
        return None, f"non-absolute profile_home {str(profile_home)!r}"
    try:
        home = candidate.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None, f"unresolvable profile_home {str(profile_home)!r}"
    if not home.is_dir():
        return None, f"profile_home is not an existing directory: {home}"
    return home, ""


def _log_rebind_skipped(reason: str) -> None:
    """Rate-limited WARNING: a malformed/untrusted profile-change payload was rejected;
    the boot binding, caches, and live config are left unchanged (fail-secure, Decision
    6). Uses the dedicated ``_last_rebind_log`` clock so a routine reload failure cannot
    suppress this operator-triggered attribution line."""
    global _last_rebind_log
    now = time.monotonic()
    with _rebind_log_lock:
        if now - _last_rebind_log < _DISARM_LOG_EVERY_S:
            return
        _last_rebind_log = now
    logger.warning("PETASOS_REBIND_SKIPPED reason=%s", reason)


def _log_rebind_config_stale(res: HermesConfigResolution, detail: str | BaseException) -> None:
    """Rate-limited WARNING: a valid re-pin landed but the heavier pipeline config did
    not apply (no ``petasos:`` section, build failure, or apply failure). The binding has
    already moved, so the armed bit honors the new profile immediately; the pipeline keeps
    last-good via ``_apply_reconfigure``'s two-phase guarantee. Loud + attributable so the
    transient armed/pipeline divergence (Decision 6) is never silent. Accepts a string
    reason or an exception so the None-path, build-failure, and apply-failure call sites
    all type-check (correctness round-3 F-1). Dedicated clock."""
    global _last_rebind_log
    now = time.monotonic()
    with _rebind_log_lock:
        if now - _last_rebind_log < _DISARM_LOG_EVERY_S:
            return
        _last_rebind_log = now
    logger.warning("PETASOS_REBIND_CONFIG_STALE path=%s: %s", res.path, detail)


def _dispatch_reconfigure(cfg: PetasosConfig, on_success, on_error) -> None:
    """Schedule ``_apply_reconfigure(cfg)`` on ``_async_loop`` WITHOUT blocking the caller
    (Decision 4). PET-126's ``_maybe_reconfigure`` blocks up to 15s on ``future.result()``;
    that is fine on the tool-call hot path but not on an operator-interactive profile-change
    callback that may run while ``_async_loop`` is busy with an ML scan. Reuses
    ``_ensure_async_loop()`` + ``run_coroutine_threadsafe`` (the guts of ``_run_async``,
    minus the blocking ``.result()``) so loop access stays single-sourced. The completion
    callback runs ``on_success`` when the apply committed or ``on_error`` if it raised —
    both on the loop thread, after ``_rebind_lock`` has been released (Decision 7)."""
    _ensure_async_loop()
    future = asyncio.run_coroutine_threadsafe(_apply_reconfigure(cfg), _async_loop)

    def _done(fut: Any) -> None:
        try:
            fut.result()
        except Exception as exc:
            on_error(exc)
        else:
            on_success()

    future.add_done_callback(_done)


def _apply_live(res: HermesConfigResolution) -> None:
    """Hot-apply the new profile via the same peek/commit sequence as
    ``_maybe_reconfigure`` (Decision 4/5). The reload cache was reset by the worker, so a
    non-empty ``petasos:`` section at the new profile reads as a change; a missing/empty/
    malformed section yields ``None`` -> keep last-good policy by design (the armed bit is
    independently re-stat'd and honored, fail-secure ``True``). Either way the outcome is
    attributable, never silent."""
    from petasos.console._reload import commit_seen, read_changed_section

    changed = read_changed_section(res)
    if changed is None:
        _log_rebind_config_stale(
            res, "no petasos: section at new profile; keeping last-good policy"
        )
        return
    section, key = changed
    try:
        cfg = _build_config_from_section(section)
    except Exception as exc:
        _log_rebind_config_stale(res, exc)
        return

    def _on_apply_error(exc: BaseException) -> None:
        # On apply failure also reset the reload cache so a stale committed key from a
        # superseded re-bind cannot suppress the next re-read (Decision 5 / Decision 7).
        from petasos.console._reload import _reset_reload_cache

        _reset_reload_cache()
        _log_rebind_config_stale(res, exc)

    _dispatch_reconfigure(
        cfg,
        on_success=lambda: commit_seen(key, res),  # settle the reload cache on the new profile
        on_error=_on_apply_error,
    )


def _rebind_to_resolution(res: HermesConfigResolution) -> None:
    """Serialized re-pin + cache reset + ``_config`` refresh + branch decision + dispatch
    (Decisions 3/5/7). ``_deferred_init`` holds ``_init_lock`` across its whole build and
    flips ``_initialized`` only at the end while still holding it, so while we hold
    ``_init_lock`` the build is never mid-flight: ``_initialized`` is either already-True
    (init done) or will-read-our-``_config`` (init not yet started). Deciding the branch
    under the SAME ``_init_lock`` acquisition makes case selection race-free, closing the
    init-window TOCTOU. Lock order is strictly ``_rebind_lock`` then ``_init_lock``
    (acyclic; ``_deferred_init`` takes only ``_init_lock``)."""
    global _session_resolution, _config
    from petasos.console._armed import _reset_armed_cache
    from petasos.console._reload import _reset_reload_cache

    with _rebind_lock:
        _session_resolution = res  # re-pin; the armed bit follows immediately
        _reset_armed_cache()  # Decision 5: drop W's (mtime,size)-keyed bit
        _reset_reload_cache()  # Decision 5: force the new profile to read as a change
        logger.info("PETASOS_ARMED_RESOLUTION tier=%s path=%s", res.tier, res.path)

        # Refresh _config AND decide the branch under the SAME _init_lock acquisition.
        with _init_lock:
            _config = _load_config(res)
            live = _initialized and _pipeline is not None and _guard is not None
            failed = (not live) and _init_error is not None

        if live:
            _apply_live(res)  # peek/build/dispatch the new profile onto the live pipeline
        elif failed:
            logger.warning(
                "PETASOS_REBIND_NOPIPELINE path=%s: init failed earlier; "
                "binding moved, no pipeline to reconfigure",
                res.path,
            )
        else:
            # Init window: _deferred_init has not yet read _config and will build from the
            # resolution we just stored. No apply here (no pipeline yet). Honest wording:
            # _deferred_init swallows a malformed section to PetasosConfig() defaults with
            # only its own generic validation log, so the binding move is attributable here
            # but the config outcome is NOT guaranteed to be the new profile's.
            logger.info(
                "PETASOS_REBIND_PENDING_INIT path=%s: scanner init in flight; new "
                "profile staged, applied at init only if it validates (else defaults)",
                res.path,
            )


def _rebind_to_profile(profile_home: Any) -> None:
    """Internal re-bind worker entry. Validates the trusted payload (fail-secure: a bad
    payload keeps the current binding, Decision 6), constructs the resolution DIRECTLY
    from the trusted home (Decision 2: never ``resolve_hermes_config_path`` /
    ``read_active_profile``), and delegates to the serialized worker."""
    home, reason = _validated_profile_home(profile_home)
    if home is None:
        _log_rebind_skipped(reason)  # binding + caches + config unchanged
        return
    from petasos.console._paths import HermesConfigResolution

    # tier="profile" is a valid Tier literal; omitting warning defaults it to None, which
    # satisfies the dataclass invariant "warning non-None only when tier=='root'".
    res = HermesConfigResolution(path=home / "config.yaml", tier="profile")
    _rebind_to_resolution(res)


def _pre_tool_call(
    tool_name: str, args: dict, task_id: str = "", **kwargs
) -> dict[str, str] | None:
    # PET-111: operator-disarmed -> zero enforcement, pass through. The gate sits
    # ABOVE _ensure_initialized so it covers the initialized, init-failed, and
    # init-in-progress windows uniformly (a disarmed boot skips the fallback scan).
    if not _is_armed():
        # PET-138: count EVERY bypassed call (authoritative tally, not a sample),
        # independent of the rate-limited heartbeat below. O(1) locked bump; no
        # scan, no _guard.evaluate — the zero-overhead disarm invariant holds.
        session_id = _derive_session_id(task_id, kwargs)
        new_count = _bump_bypass_count(session_id)
        # PET-131: emit a "bypassed (disarmed)" event 1:1 with the rate-limited
        # PETASOS_DISARMED log line so the operator can confirm "off means off".
        # PET-138: carry the cumulative per-session count on that heartbeat.
        if _log_disarmed_bypass(tool_name):
            _emit_enforcement_event(
                session_id=session_id,
                tool=tool_name,
                event_type="bypassed_disarmed",
                armed=False,
                bypassed_count=new_count,
            )
        return None
    if not _ensure_initialized():
        if _init_error:
            logger.debug("Petasos init failed — allowing tool call")
            return None
        # Init still in progress — use MinimalScanner fallback so we don't
        # silently allow during the cold-start window (fail_mode=closed
        # means we should be blocking, not passing through).
        return _fallback_pre_tool_call(tool_name, args, task_id, **kwargs)

    # PET-126: initialized here — pick up any live config.yaml change before this
    # call is evaluated. Self-guarded and fail-safe; never blocks the tool call.
    try:
        _maybe_reconfigure()
    except Exception as exc:
        logger.debug("Petasos reconfigure check failed: %s — keeping last-good", exc)

    session_id = _derive_session_id(task_id, kwargs)

    try:
        result = _run_async(_guard.evaluate(tool_name, args, session_id))
    except Exception as exc:
        logger.error("Petasos guard evaluation failed: %s — allowing tool call", exc)
        return None

    if result.tier == "tier3":
        logger.critical(
            "PETASOS_TIER3 tool=%s session=%s — all tool calls blocked", tool_name, session_id
        )
        _emit_enforcement_event(
            session_id=session_id, tool=tool_name, event_type="tier3", tier="tier3"
        )
        return {
            "action": "block",
            "message": format_block_message(result, tool_name),  # PET-77
        }

    if not result.allowed:
        logger.warning(
            "PETASOS_BLOCK tool=%s session=%s reason=%s", tool_name, session_id, result.reason
        )
        _emit_enforcement_event(
            session_id=session_id,
            tool=tool_name,
            event_type="block",
            tier=result.tier,
            reason=result.reason,
        )
        # PET-77: route through the formatter so internal reason strings (exempt-with-scan,
        # tier2: tool calls blocked, ...) never reach the model. (The enforcement event
        # above carries the raw reason to the OPERATOR dashboard, not the model.)
        return {"action": "block", "message": format_block_message(result, tool_name)}

    # PET-112: read-only tools never take a content block (both old blocks were
    # _is_dangerous-gated; preserved exactly).
    if not _is_dangerous(tool_name):
        return None

    egress = _is_egress_sink(tool_name)
    # HIGH/CRITICAL only, via the ordinal gate (D-CAVEAT) — partitioned by finding type.
    blocking = [f for f in result.findings if _blocks(f.severity)]
    non_pii_blocking = [f for f in blocking if f.finding_type != "pii"]
    pii_blocking = [f for f in blocking if f.finding_type == "pii"]

    # 0. PET-134 source-taint egress fence: the FIRST block check, additive to and
    #    independent of the PII-egress block below. Content a tool in a declared source
    #    namespace returned may not leave, verbatim, via an egress sink, regardless of
    #    whether it also matches PII. All three short-circuits collapse to a fast empty-set
    #    check on the default, so the feature-off / untainted path is byte-identical to the
    #    pre-PET-134 behavior. Direction-orthogonal: tainted_source is a pure substring
    #    test that never consults Direction and never calls the pipeline scan. The
    #    model-facing message carries no source/sink detail (PET-77); the provenance
    #    namespace and sink go only to the operator log line + enforcement event (D-OBSERV).
    if egress and _source_taint_namespaces and _taint_store is not None:
        tainted_ns = _taint_store.tainted_source(session_id, args)
        if tainted_ns is not None:
            reason = f"source-taint egress: {tainted_ns} -> {tool_name}"
            logger.warning(
                "PETASOS_QUARANTINE tool=%s session=%s — %s", tool_name, session_id, reason
            )
            _emit_enforcement_event(
                session_id=session_id,
                tool=tool_name,
                event_type="quarantine",
                reason=reason,
            )
            return {
                "action": "block",
                "message": format_content_block("taint_egress", tool_name, ()),
            }

    # 1. Scan degraded/unreliable -> block ALL dangerous tools (fail-mode; cannot trust the
    #    scan). Independent of finding type, so a degraded scanner co-occurring with a PII
    #    finding still blocks (D-DEGRADED, closes the degraded+PII hole).
    if result.param_scan_degraded:
        logger.warning(
            "PETASOS_QUARANTINE tool=%s session=%s — param scan degraded",
            tool_name,
            session_id,
        )
        _emit_enforcement_event(
            session_id=session_id,
            tool=tool_name,
            event_type="quarantine",
            param_scan_degraded=True,
            reason="param scan degraded",
        )
        return {
            "action": "block",
            "message": format_content_block("degraded", tool_name, tuple(blocking)),  # PET-77
        }

    # 2. Non-PII finding (injection/command/structural/credential) at HIGH+ -> block ALL
    #    dangerous tools (D3 posture; credentials are deliberately NOT egress-scoped).
    if non_pii_blocking:
        worst = _worst(non_pii_blocking)
        logger.warning(
            "PETASOS_QUARANTINE tool=%s session=%s — %s finding: %s",
            tool_name,
            session_id,
            worst.severity.name,
            worst.message,
        )
        _emit_enforcement_event(
            session_id=session_id,
            tool=tool_name,
            event_type="quarantine",
            severity=worst.severity.name,
            rule_id=worst.rule_id,
            reason=worst.message,
        )
        return {
            "action": "block",
            "message": format_content_block("non_pii_param", tool_name, tuple(non_pii_blocking)),
        }

    # 3. PII at HIGH+ -> block ONLY egress sinks (D-EGRESS). Internal tools are exempt, so
    #    an agent's own local write/terminal/edit of PII is permitted.
    if pii_blocking and egress:
        worst = _worst(pii_blocking)
        logger.warning(
            "PETASOS_QUARANTINE tool=%s session=%s — PII to egress sink: %s",
            tool_name,
            session_id,
            worst.message,
        )
        _emit_enforcement_event(
            session_id=session_id,
            tool=tool_name,
            event_type="quarantine",
            severity=worst.severity.name,
            rule_id=worst.rule_id,
            reason=worst.message,
        )
        return {
            "action": "block",
            "message": format_content_block("pii_egress", tool_name, tuple(pii_blocking)),
        }

    return None


def _post_tool_call(
    tool_name: str, args: dict, result: str = "", task_id: str = "", duration_ms: int = 0, **kwargs
) -> None:
    if not _initialized:
        return
    if not _is_armed():  # PET-111: skip the completion log while disarmed
        return
    logger.debug("PETASOS_TOOL_COMPLETE tool=%s duration_ms=%d", tool_name, duration_ms)

    # PET-134: capture tainted spans from a declared source namespace. Fast-path off on the
    # empty default (zero added cost, preserves the no-op posture, brief D-PERF). Guarded
    # end-to-end so capture can never break a completing tool call.
    if not _source_taint_namespaces or _taint_store is None:
        return
    try:
        source_ns = _match_source_namespace(tool_name)
        if source_ns is None:
            return
        # D1b: skip capture when no stable correlator was supplied. That input shape
        # (no task_id and no _agent) drives _derive_session_id into a fresh anon-<uuid>
        # per call that a later _pre_tool_call check can never match, so storing under it
        # is a guaranteed fail-open plus orphan-session growth. The discriminator is the
        # INPUTS, not the derived-id string: a durable task_id that legitimately begins
        # with "anon-" stays correlatable and is captured.
        if not task_id and kwargs.get("_agent") is None:
            return
        _taint_store.capture(_derive_session_id(task_id, kwargs), result, source_ns)
    except Exception as exc:
        logger.debug("Petasos taint capture failed: %s; skipping", exc)


def _on_session_start(**kwargs) -> None:
    logger.info("PETASOS_SESSION_START — Petasos content security active")


def _on_profile_change(profile_name: str = "", profile_home: str = "", **kwargs: Any) -> None:
    """PET-132: trusted Hermes profile-change signal. Hermes fires this only from the
    operator-trusted swap path with the new profile's home; Petasos does not re-derive the
    identity (Decision 2). ``profile_name`` is cosmetic and logged via ``%r`` (repr escapes
    any newline/control char) so a crafted name cannot inject a forged
    ``PETASOS_ARMED_RESOLUTION`` line; the load-bearing identity is the path, logged
    separately by the worker (Decision 6). Registered defensively via _try_register_hook,
    so a host without the event simply never calls it (dormant, safe)."""
    logger.info("PETASOS_PROFILE_CHANGE name=%r", profile_name or "<unnamed>")
    _rebind_to_profile(profile_home)


def _subagent_start(parent_session_id: str = "", child_session_id: str = "", **kwargs) -> None:
    """Host-asserted lineage edge: child spawned by parent (PET-107 D2).

    Only the host's hook calls register(); the child agent never registers its
    own edge and does not choose its parent_session_id (Hermes assigns it from
    the spawning parent). The untrusted surface is the child's tool *content*
    (already scanned), not this edge.
    """
    reg = _lineage_registry
    if reg is None:
        return
    if not child_session_id or not parent_session_id:
        logger.debug("subagent_start missing parent/child id — ignoring edge")
        return
    reg.register(child_session_id, parent_session_id)


def _subagent_stop(child_session_id: str = "", **kwargs) -> None:
    """Drop the child's lineage edge on stop (idempotent)."""
    reg = _lineage_registry
    if reg is None:
        return
    if child_session_id:
        reg.unregister(child_session_id)


def _try_register_hook(ctx, name: str, handler) -> bool:
    """Register an optional hook, tolerating a host that rejects the name.

    subagent_start/subagent_stop are a Hermes-side assumption (brief
    delegate_tool.py:1213) that must be verified against the live build. If the
    host's plugin loader rejects the name, log a warning and report False so the
    caller can degrade A → C rather than crash.
    """
    try:
        ctx.register_hook(name, handler)
        return True
    except Exception as exc:
        logger.warning("register_hook(%s) rejected by host — skipping: %s", name, exc)
        return False


# ---------------------------------------------------------------------------
# Plugin registration — called by Hermes plugin loader
# ---------------------------------------------------------------------------


def register(ctx) -> None:
    global _config, _subagent_hooks_available, _session_resolution
    global _hooks_registered, _init_thread_started

    # PET-132: a re-runnable register() is the forced-rediscovery re-bind route (Decision
    # 1 fallback / Decision 3). The FIRST register() of an uninitialized process spawns
    # _deferred_init; a SECOND one (Hermes re-ran discovery under the new profile env)
    # must re-bind the live pipeline instead of double-registering hooks or spawning a
    # duplicate init thread. Latch the boot-vs-rebind decision BEFORE the flags move.
    first_boot = not _init_thread_started and not _initialized and not _init_error

    # PET-130: capture the session-bound resolution FIRST — before any hook is
    # registered or the init thread starts — so the first _pre_tool_call cannot
    # observe a None binding and fall back to an ambient resolve. Pre-clear to None
    # so a re-register whose capture fails cannot leave a stale prior binding. The
    # binding source is the operator-trusted boot environment, never in-session
    # state (PET-125 / Decision 2). On the forced-rediscovery route Hermes has set the
    # env to the new profile, so this re-captures the new profile here too.
    _session_resolution = None
    try:
        from petasos.console._paths import resolve_hermes_config_path

        _session_resolution = resolve_hermes_config_path()
    except Exception as exc:  # resolve_hermes_config_path never raises; stay safe
        logger.warning(
            "PETASOS_ARMED_RESOLUTION tier=unresolved path=ambient: boot capture "
            "failed (%s); falling back to per-call resolve",
            exc,
        )
    if first_boot and _session_resolution is not None:
        # D2: greppable, names the tier + absolute path the armed/reload reads pin to.
        # On a re-register the worker (below) re-emits this line after re-pinning, so it
        # is logged exactly once per register() either way.
        logger.info(
            "PETASOS_ARMED_RESOLUTION tier=%s path=%s",
            _session_resolution.tier,
            _session_resolution.path,
        )

    try:
        _config = _load_config(_session_resolution)
    except Exception as exc:
        logger.error("Failed to load petasos config: %s", exc)
        _config = {}

    # PET-132: register every hook exactly once per process (Decision 3). The already-
    # registered closures read the module globals (_session_resolution, _config,
    # _pipeline, _guard) dynamically, so a re-register's new binding is observed without
    # re-registration; a second register() onto a fresh ctx intentionally skips it.
    if not _hooks_registered:
        ctx.register_hook("pre_tool_call", _pre_tool_call)
        ctx.register_hook("post_tool_call", _post_tool_call)
        ctx.register_hook("on_session_start", _on_session_start)

        # PET-107: sub-agent lineage hooks (Option A). Registered defensively — both
        # must be accepted, else A degrades fully to C (an edge store that never sees
        # subagent_stop would leak edges to the TTL/on_terminate backstop only).
        start_ok = _try_register_hook(ctx, "subagent_start", _subagent_start)
        stop_ok = _try_register_hook(ctx, "subagent_stop", _subagent_stop)
        _subagent_hooks_available = start_ok and stop_ok
        if not _subagent_hooks_available:
            rejected = [
                name
                for name, ok in (("subagent_start", start_ok), ("subagent_stop", stop_ok))
                if not ok
            ]
            logger.warning(
                "Petasos sub-agent lineage (A) inactive — hook(s) unavailable: %s. "
                "Delegation fan-out gate (C) remains active.",
                ", ".join(rejected),
            )

        # PET-132: the trusted profile-change re-bind hook. Registered defensively so a
        # host without on_profile_change degrades to "restart required" (Decision 8)
        # rather than crashing; on every host today it is simply never fired (dormant).
        _try_register_hook(ctx, "on_profile_change", _on_profile_change)

        _hooks_registered = True

    if first_boot:
        _init_thread_started = True
        init_thread = threading.Thread(
            target=_deferred_init,
            daemon=True,
            name="petasos-init",
        )
        init_thread.start()
        logger.info("Petasos plugin registered — hooks active, scanner init in background")
    elif _session_resolution is not None:
        # Forced-rediscovery re-register of an already-started process: re-bind the live
        # pipeline to the freshly-captured resolution (re-pin, reset the (mtime,size)-keyed
        # caches, re-emit ARMED_RESOLUTION, hot-apply / stage per init state). The init
        # thread is NOT re-spawned (Decision 3).
        _rebind_to_resolution(_session_resolution)
        logger.info("Petasos plugin re-registered — re-bound to the current profile resolution")
    else:
        logger.warning(
            "Petasos re-register: boot capture failed and no prior binding to re-bind; "
            "enforcement reflects the last good binding until restart"
        )
