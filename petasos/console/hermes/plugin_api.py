"""Hermes Dashboard plugin backend — APIRouter delegating to ConsoleHandlers.

Routes mount at /api/plugins/petasos/ via Hermes's plugin discovery.
The Pipeline instance is obtained from the Hermes plugin context at init time.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter()

_handlers = None


def init_handlers(pipeline: Any) -> None:
    """Called by the Hermes plugin init hook to wire the Pipeline."""
    global _handlers  # noqa: PLW0603
    from petasos.console.server import ConsoleHandlers

    _handlers = ConsoleHandlers(pipeline)


@router.get("/config")
async def get_config() -> Any:
    assert _handlers is not None, "plugin_api not initialized — call init_handlers(pipeline) first"
    return await _handlers.get_config()


@router.put("/config")
async def update_config(request: Request) -> Any:
    assert _handlers is not None
    body = await request.json()
    result, errors = await _handlers.update_config(body)
    if errors is not None:
        return JSONResponse(status_code=422, content={"detail": errors})
    return result


@router.post("/scan")
async def run_scan(request: Request) -> Any:
    assert _handlers is not None
    body = await request.json()
    text = body.get("text", "")
    if not text or not text.strip():
        return JSONResponse(status_code=422, content={"detail": [{"field": "text", "message": "Text must not be empty"}]})
    if len(text) > 100_000:
        return JSONResponse(status_code=422, content={"detail": [{"field": "text", "message": "Text exceeds 100000 character limit"}]})
    return await _handlers.run_scan(text, direction=body.get("direction", "inbound"), session_id=body.get("session_id"))


@router.get("/health")
async def get_health() -> Any:
    assert _handlers is not None
    return await _handlers.get_health()


@router.get("/scan-history")
async def get_scan_history(limit: int = 100) -> Any:
    assert _handlers is not None
    return await _handlers.get_scan_history(limit)


@router.get("/profiles")
async def get_profiles() -> Any:
    assert _handlers is not None
    return await _handlers.get_profiles()


@router.get("/events")
async def events() -> StreamingResponse:
    assert _handlers is not None
    q = _handlers.sse.subscribe()
    return StreamingResponse(
        _handlers.sse.stream(q),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/about")
async def get_about() -> Any:
    assert _handlers is not None
    return await _handlers.get_about()
