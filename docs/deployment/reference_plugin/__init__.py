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
import logging
import os
import threading
import uuid
from typing import Any

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


def _is_dangerous(tool_name: str) -> bool:
    return tool_name not in READ_ONLY_TOOLS


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
            enabled = raw_config.pop("enabled", True)

            if not enabled:
                logger.info("Petasos disabled via config (enabled: false)")
                _init_error = "disabled"
                return

            session_secret_b64 = os.environ.get("PETASOS_SESSION_SECRET")
            session_secret = None
            if session_secret_b64:
                try:
                    session_secret = base64.b64decode(session_secret_b64)
                except Exception:
                    logger.warning(
                        "PETASOS_SESSION_SECRET is not valid base64"
                        " — HMAC session binding disabled"
                    )
            else:
                logger.warning("PETASOS_SESSION_SECRET not set — HMAC session binding disabled")

            hash_key = os.environ.get("PETASOS_HASH_KEY")
            if not hash_key and raw_config.get("redaction_mode") == "hash":
                logger.warning(
                    "PETASOS_HASH_KEY not set but redaction_mode=hash "
                    "— PII anonymization will fail. Set PETASOS_HASH_KEY "
                    "or change redaction_mode."
                )
                raw_config["anonymize"] = False

            if session_secret is not None:
                raw_config["session_secret"] = session_secret
            if hash_key:
                raw_config["hash_key"] = hash_key

            try:
                config = PetasosConfig.from_dict(raw_config)
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

            from petasos import FrequencyTracker

            tracker = FrequencyTracker(config)
            _guard = ToolCallGuard(_pipeline, tracker, config)

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
            from petasos._types import Severity

            worst = max(result.findings, key=lambda f: f.severity.value)
            if worst.severity.value >= Severity.HIGH.value:
                logger.warning(
                    "PETASOS_FALLBACK_BLOCK tool=%s — init in progress, syntactic scan found: %s",
                    tool_name,
                    worst.rule_id,
                )
                return {
                    "action": "block",
                    "message": (f"Security scan (init in progress): {worst.message}"),
                }
    except Exception as exc:
        logger.debug("Fallback scan failed: %s — allowing", exc)
    return None


def _pre_tool_call(
    tool_name: str, args: dict, task_id: str = "", **kwargs
) -> dict[str, str] | None:
    if not _ensure_initialized():
        if _init_error == "disabled":
            return None
        if _init_error:
            logger.debug("Petasos init failed — allowing tool call")
            return None
        # Init still in progress — use MinimalScanner fallback so we don't
        # silently allow during the cold-start window (fail_mode=closed
        # means we should be blocking, not passing through).
        return _fallback_pre_tool_call(tool_name, args, task_id, **kwargs)

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
            "message": (
                "All tool calls blocked for this session by security policy (Tier 3 escalation)."
            ),
        }

    if not result.allowed:
        logger.warning(
            "PETASOS_BLOCK tool=%s session=%s reason=%s", tool_name, session_id, result.reason
        )
        return {"action": "block", "message": result.reason}

    if result.param_scan_unsafe and _is_dangerous(tool_name):
        logger.warning(
            "PETASOS_QUARANTINE tool=%s session=%s — param scan unsafe on non-read-only tool",
            tool_name,
            session_id,
        )
        return {
            "action": "block",
            "message": f"Parameter scan flagged unsafe content: {result.reason}",
        }

    if result.findings and _is_dangerous(tool_name):
        from petasos._types import Severity

        worst = max(result.findings, key=lambda f: f.severity.value)
        if worst.severity.value >= Severity.HIGH.value:
            logger.warning(
                "PETASOS_QUARANTINE tool=%s session=%s — %s finding: %s",
                tool_name,
                session_id,
                worst.severity.name,
                worst.message,
            )
            return {
                "action": "block",
                "message": (f"Security finding ({worst.severity.name}): {worst.message}"),
            }

    return None


def _post_tool_call(
    tool_name: str, args: dict, result: str = "", task_id: str = "", duration_ms: int = 0, **kwargs
) -> None:
    if not _initialized:
        return
    logger.debug("PETASOS_TOOL_COMPLETE tool=%s duration_ms=%d", tool_name, duration_ms)


def _on_session_start(**kwargs) -> None:
    logger.info("PETASOS_SESSION_START — Petasos content security active")


# ---------------------------------------------------------------------------
# Plugin registration — called by Hermes plugin loader
# ---------------------------------------------------------------------------


def register(ctx) -> None:
    global _config

    try:
        _config = _load_config()
    except Exception as exc:
        logger.error("Failed to load petasos config: %s", exc)
        _config = {}

    ctx.register_hook("pre_tool_call", _pre_tool_call)
    ctx.register_hook("post_tool_call", _post_tool_call)
    ctx.register_hook("on_session_start", _on_session_start)

    init_thread = threading.Thread(
        target=_deferred_init,
        daemon=True,
        name="petasos-init",
    )
    init_thread.start()

    logger.info("Petasos plugin registered — hooks active, scanner init in background")
