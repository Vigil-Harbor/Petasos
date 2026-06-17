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
from typing import TYPE_CHECKING, Any

from petasos._types import Severity  # PET-112: dep-light (enum + dataclasses, no ML imports)
from petasos.normalize import canonicalize_tool_name  # PET-118: dep-light (re + unicodedata)
from petasos.session.formatting import (  # PET-77: dep-light (string formatting over dataclasses)
    format_block_message,
    format_content_block,
)

if TYPE_CHECKING:
    from petasos import PetasosConfig

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

# PET-111: live arm/disarm. _pre_tool_call/_post_tool_call re-read petasos.enabled
# per call (mtime+size+TTL-cached in petasos.console._armed) rather than latching
# it at init, so an operator's Equipped/Unequipped toggle affects running sessions.
# The disarm tripwire is rate-limited so a bypass of (even tier-3) enforcement is
# always attributable in the log.
_disarm_log_lock = threading.Lock()
_last_disarm_log = 0.0
_DISARM_LOG_EVERY_S = 30.0

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


def _load_config() -> dict[str, Any]:
    """Read petasos: section from the resolved Hermes config.yaml."""
    from petasos.console._paths import read_petasos_section, resolve_hermes_config_path

    res = resolve_hermes_config_path()
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

            from petasos import FrequencyTracker, LineageRegistry

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
        if agent_id not in _session_ids:
            _session_ids[agent_id] = f"desktop-{uuid.uuid4().hex[:12]}"
        return _session_ids[agent_id]
    return f"anon-{uuid.uuid4().hex[:8]}"


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
    """PET-111: True unless the operator set petasos.enabled=false. Fail-secure True."""
    try:
        from petasos.console._armed import read_armed

        return read_armed()
    except Exception:
        return True  # never fail open into disarmed


def _reset_disarm_log() -> None:
    """Test seam — reset the disarm tripwire rate-limit clock."""
    global _last_disarm_log
    with _disarm_log_lock:
        _last_disarm_log = 0.0


def _log_disarmed_bypass(tool_name: str) -> None:
    """Rate-limited WARNING so an operator-disarmed bypass is always attributable."""
    global _last_disarm_log
    now = time.monotonic()
    with _disarm_log_lock:
        if now - _last_disarm_log < _DISARM_LOG_EVERY_S:
            return
        _last_disarm_log = now
    logger.warning(
        "PETASOS_DISARMED tool=%s — enforcement bypassed by operator (Unequipped)",
        tool_name,
    )


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
    global _egress_sink_tools
    _egress_sink_tools = frozenset(
        c for c in (canonicalize_tool_name(t) for t in cfg.egress_sink_tools) if c
    )


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

    changed = read_changed_section()
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
    commit_seen(key)
    _log_reconfigure_applied()


def _pre_tool_call(
    tool_name: str, args: dict, task_id: str = "", **kwargs
) -> dict[str, str] | None:
    # PET-111: operator-disarmed -> zero enforcement, pass through. The gate sits
    # ABOVE _ensure_initialized so it covers the initialized, init-failed, and
    # init-in-progress windows uniformly (a disarmed boot skips the fallback scan).
    if not _is_armed():
        _log_disarmed_bypass(tool_name)
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
        return {
            "action": "block",
            "message": format_block_message(result, tool_name),  # PET-77
        }

    if not result.allowed:
        logger.warning(
            "PETASOS_BLOCK tool=%s session=%s reason=%s", tool_name, session_id, result.reason
        )
        # PET-77: route through the formatter so internal reason strings (exempt-with-scan,
        # tier2: tool calls blocked, ...) never reach the model.
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

    # 1. Scan degraded/unreliable -> block ALL dangerous tools (fail-mode; cannot trust the
    #    scan). Independent of finding type, so a degraded scanner co-occurring with a PII
    #    finding still blocks (D-DEGRADED, closes the degraded+PII hole).
    if result.param_scan_degraded:
        logger.warning(
            "PETASOS_QUARANTINE tool=%s session=%s — param scan degraded",
            tool_name,
            session_id,
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


def _on_session_start(**kwargs) -> None:
    logger.info("PETASOS_SESSION_START — Petasos content security active")


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
    global _config, _subagent_hooks_available

    try:
        _config = _load_config()
    except Exception as exc:
        logger.error("Failed to load petasos config: %s", exc)
        _config = {}

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

    init_thread = threading.Thread(
        target=_deferred_init,
        daemon=True,
        name="petasos-init",
    )
    init_thread.start()

    logger.info("Petasos plugin registered — hooks active, scanner init in background")
