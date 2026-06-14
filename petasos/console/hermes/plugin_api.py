"""Hermes Dashboard plugin backend — APIRouter delegating to ConsoleHandlers.

Routes mount at /api/plugins/petasos/ via Hermes's plugin discovery.

The dashboard process is separate from the agent process, so we cannot
rely on a shared Pipeline reference. Instead, _require_handlers() builds
its own read-only Pipeline from config.yaml on first API call.

This module requires fastapi at runtime (Hermes installs it).
The petasos.console.* mypy override suppresses import-not-found
so CI typecheck passes without the console extra installed.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from petasos.console._paths import read_petasos_section, resolve_hermes_config_path
from petasos.console._validation import SessionIdError, sanitize_session_id

logger = logging.getLogger("petasos.dashboard")

router = APIRouter()

_handlers: Any = None

_VALID_DIRECTIONS = frozenset({"inbound", "outbound"})


def init_handlers(pipeline: Any) -> None:
    """Wire a Pipeline instance into the dashboard API."""
    global _handlers  # noqa: PLW0603
    from petasos.console.server import ConsoleHandlers

    _handlers = ConsoleHandlers(pipeline)


def _load_config() -> dict[str, Any]:
    """Read petasos: section from the resolved Hermes config.yaml."""
    res = resolve_hermes_config_path()
    logger.info("loading config from %s [tier=%s]", res.path, res.tier)
    if res.warning:
        logger.warning("Hermes profile resolution: %s", res.warning)
    section = read_petasos_section(res)
    if not res.path.is_file():
        logger.warning("Hermes config not found at %s — using Petasos defaults", res.path)
    return section


def _self_init() -> None:
    """Build a standalone Pipeline for the dashboard process."""
    import base64

    from petasos import PetasosConfig, Pipeline
    from petasos.scanners import MinimalScanner

    raw_config = _load_config()
    raw_config.pop("host_id", None)
    raw_config.pop("enabled", None)

    session_secret_b64 = os.environ.get("PETASOS_SESSION_SECRET")
    if session_secret_b64:
        try:
            raw_config["session_secret"] = base64.b64decode(session_secret_b64)
        except Exception as exc:
            logger.warning(
                "PETASOS_SESSION_SECRET is not valid base64 — session binding disabled: %s",
                exc,
            )

    hash_key = os.environ.get("PETASOS_HASH_KEY")
    if hash_key:
        raw_config["hash_key"] = hash_key

    try:
        config = PetasosConfig.from_dict(raw_config)
    except (TypeError, ValueError):
        config = PetasosConfig()

    scanners = [MinimalScanner(decode_encoded_payloads=config.decode_encoded_payloads)]
    unavailable: list[str] = []
    for name, cls_path in [
        ("LLM Guard", "petasos.scanners.LlmGuardScanner"),
        ("LlamaFirewall", "petasos.scanners.LlamaFirewallScanner"),
        ("Presidio", "petasos.scanners.PresidioScanner"),
    ]:
        try:
            mod, cls = cls_path.rsplit(".", 1)
            import importlib

            m = importlib.import_module(mod)
            instance = getattr(m, cls)()
            scanners.append(instance)
            probe = getattr(instance, "availability", None)
            if probe is not None:
                # PET-103 D4: arity-tolerant extraction — availability() is
                # duck-typed here (getattr), so tolerate both the legacy 2-tuple
                # and the widened 3-tuple (ok, reason, cause).
                probe_result = probe()
                avail = bool(probe_result[0])
                reason = probe_result[1] if len(probe_result) > 1 else None
                if avail:
                    logger.info("Dashboard scanner %s: backend verified", name)
                else:
                    unavailable.append(name)
                    logger.warning(
                        "Dashboard scanner %s: backend missing — registered degraded: %s",
                        name,
                        reason,
                    )
            else:
                logger.info("Dashboard scanner %s: backend verified", name)
        except ImportError:
            unavailable.append(name)
            logger.warning("Dashboard scanner %s: import failed", name)
        except Exception as exc:
            unavailable.append(name)
            logger.warning("Dashboard scanner %s failed: %s", name, exc)

    pipeline = Pipeline(config=config, scanners=scanners, host_id="dashboard")

    license_key = os.environ.get("PETASOS_LICENSE_KEY")
    if license_key:
        pipeline.activate(license_key)

    init_handlers(pipeline)
    logger.info(
        "Dashboard self-initialized pipeline: scanners=%s, unavailable=%s",
        [s.name for s in scanners],
        unavailable,
    )


def _require_handlers() -> Any:
    global _handlers
    if _handlers is None:
        try:
            import petasos.console as _console

            if _console._shared_pipeline is not None:
                init_handlers(_console._shared_pipeline)
        except Exception:
            pass
    if _handlers is None:
        try:
            _self_init()
        except Exception as exc:
            logger.error("Dashboard self-init failed: %s", exc, exc_info=True)
    if _handlers is None:
        raise HTTPException(
            status_code=503,
            detail="plugin API not initialized — pipeline not yet ready",
        )
    return _handlers


@router.get("/config")
async def get_config() -> Any:
    h = _require_handlers()
    return await h.get_config()


@router.put("/config")
async def update_config(request: Request) -> Any:
    from fastapi.responses import JSONResponse

    h = _require_handlers()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=422,
            content={"detail": [{"field": "body", "message": "Invalid JSON"}]},
        )
    if not isinstance(body, dict):
        return JSONResponse(
            status_code=422,
            content={"detail": [{"field": "body", "message": "Expected JSON object"}]},
        )
    result, errors = await h.update_config(body)
    if errors is not None:
        return JSONResponse(status_code=422, content={"detail": errors})
    return result


@router.post("/scan")
async def run_scan(request: Request) -> Any:
    from fastapi.responses import JSONResponse

    h = _require_handlers()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=422,
            content={"detail": [{"field": "body", "message": "Invalid JSON"}]},
        )
    if not isinstance(body, dict):
        return JSONResponse(
            status_code=422,
            content={"detail": [{"field": "body", "message": "Expected JSON object"}]},
        )
    text = body.get("text", "")
    if not isinstance(text, str) or not text.strip():
        err = {"field": "text", "message": "Text must be a non-empty string"}
        return JSONResponse(status_code=422, content={"detail": [err]})
    if len(text) > 100_000:
        err = {"field": "text", "message": "Text exceeds 100000 character limit"}
        return JSONResponse(status_code=422, content={"detail": [err]})
    direction = body.get("direction", "inbound")
    if not isinstance(direction, str) or direction not in _VALID_DIRECTIONS:
        err = {"field": "direction", "message": "Must be 'inbound' or 'outbound'"}
        return JSONResponse(status_code=422, content={"detail": [err]})
    try:
        session_id = sanitize_session_id(body.get("session_id"))
    except SessionIdError as exc:
        err = {"field": "session_id", "message": str(exc)}
        return JSONResponse(status_code=422, content={"detail": [err]})
    return await h.run_scan(text, direction=direction, session_id=session_id)


@router.get("/health")
async def get_health() -> Any:
    return await _require_handlers().get_health()


@router.get("/scan-history")
async def get_scan_history(limit: int = 100) -> Any:
    return await _require_handlers().get_scan_history(limit)


@router.get("/profiles")
async def get_profiles() -> Any:
    return await _require_handlers().get_profiles()


@router.get("/events")
async def events() -> Any:
    from fastapi.responses import StreamingResponse

    h = _require_handlers()
    q = h.sse.subscribe()
    return StreamingResponse(
        h.sse.stream(q),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/about")
async def get_about() -> Any:
    return await _require_handlers().get_about()


@router.get("/diag")
async def get_diag() -> Any:
    """Debug endpoint — pipeline wiring diagnostics."""
    return {"handlers_ready": _handlers is not None}
