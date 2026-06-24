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
    """Build a standalone Pipeline for the dashboard process.

    Seam pin (PET-153): config still resolves through this module's
    ``_load_config()`` (the seam ``tests/test_plugin_init_logging.py``
    monkeypatches), and the resulting dict feeds the shared
    ``build_dashboard_pipeline`` builder so the embedded dashboard plugin and the
    out-of-process standalone console (``petasos.console.__main__``) construct
    identical pipelines with no drift. The scanner build, probe logging, env-secret
    injection, and self-initialized summary all live in the builder now.
    """
    from petasos.console._standalone import build_dashboard_pipeline

    raw_config = _load_config()
    pipeline = build_dashboard_pipeline(raw_config)
    init_handlers(pipeline)


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
async def get_config(profile: str | None = None) -> Any:
    # PET-146 (edge F-1): the embedded Hermes-desktop bridge MUST forward the
    # ?profile=<name> selector — this is the primary operator surface; without it
    # the selector silently no-ops there. The PUT bridge below already forwards the
    # body unchanged (the selector rides as a top-level body key, popped in the
    # shared handler), so only this GET needs the explicit query param.
    from fastapi.responses import JSONResponse

    from petasos.console.server import ProfileNotFoundError

    h = _require_handlers()
    # CodeRabbit PR #135: an unresolved selector is a structured 422, not a silent
    # fallback to the equipped view (mirrors the standalone route + the PUT contract).
    try:
        return await h.get_config(profile=profile)
    except ProfileNotFoundError as exc:
        return JSONResponse(
            status_code=422,
            content={"detail": [{"field": "profile", "message": str(exc)}]},
        )


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
    try:
        return await h.run_scan(text, direction=direction, session_id=session_id)
    except Exception as exc:  # PET-99 D8: defense-in-depth; pipeline.inspect never throws
        logger.exception("console scan failed")
        return JSONResponse(
            status_code=500,
            content={"detail": [{"field": "scan", "message": str(exc)}]},
        )


@router.get("/health")
async def get_health() -> Any:
    return await _require_handlers().get_health()


@router.get("/scan-history")
async def get_scan_history(limit: int = 100, before: str | None = None) -> Any:
    # PET-148: additive `before` cursor for back-pages; absent => today's live window.
    return await _require_handlers().get_scan_history(limit, before)


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


@router.get("/armed")
async def get_armed() -> Any:
    return await _require_handlers().get_armed()


@router.post("/armed")
async def set_armed(request: Request) -> Any:
    from fastapi.responses import JSONResponse

    h = _require_handlers()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=422,
            content={"detail": [{"field": "body", "message": "Invalid JSON"}]},
        )
    if not isinstance(body, dict) or not isinstance(body.get("armed"), bool):
        return JSONResponse(
            status_code=422,
            content={"detail": [{"field": "armed", "message": "Must be a boolean"}]},
        )
    result, ok = await h.set_armed(body["armed"])
    if not ok:
        return JSONResponse(
            status_code=503,
            content={
                "detail": [{"field": "armed", "message": "Failed to persist armed state to disk"}]
            },
        )
    return result


@router.get("/diag")
async def get_diag() -> Any:
    """Debug endpoint — pipeline wiring diagnostics."""
    return {"handlers_ready": _handlers is not None}
