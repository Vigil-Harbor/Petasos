"""Hermes Dashboard plugin backend — APIRouter delegating to ConsoleHandlers.

Routes mount at /api/plugins/petasos/ via Hermes's plugin discovery.
The Pipeline instance is obtained from the Hermes plugin context at init time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import Request

try:
    from fastapi import APIRouter, HTTPException

    router: APIRouter | None = APIRouter()
except ImportError:
    HTTPException = None  # type: ignore[assignment,misc]
    router = None

_handlers: Any = None

_VALID_DIRECTIONS = frozenset({"inbound", "outbound"})


def init_handlers(pipeline: Any) -> None:
    """Called by the Hermes plugin init hook to wire the Pipeline."""
    global _handlers  # noqa: PLW0603
    from petasos.console.server import ConsoleHandlers

    _handlers = ConsoleHandlers(pipeline)


def _require_handlers() -> Any:
    if _handlers is None:
        if HTTPException is not None:
            raise HTTPException(
                status_code=503,
                detail="plugin API not initialized — call init_handlers(pipeline) first",
            )
        raise RuntimeError("plugin API not initialized")
    return _handlers


if router is not None:

    @router.get("/config")
    async def get_config() -> Any:
        h = _require_handlers()
        return await h.get_config()

    @router.put("/config")
    async def update_config(request: Request) -> Any:
        from fastapi.responses import JSONResponse as _JSONResponse

        h = _require_handlers()
        try:
            body = await request.json()
        except Exception:
            return _JSONResponse(
                status_code=422,
                content={"detail": [{"field": "body", "message": "Invalid JSON"}]},
            )
        if not isinstance(body, dict):
            return _JSONResponse(
                status_code=422,
                content={"detail": [{"field": "body", "message": "Expected JSON object"}]},
            )
        result, errors = await h.update_config(body)
        if errors is not None:
            return _JSONResponse(status_code=422, content={"detail": errors})
        return result

    @router.post("/scan")
    async def run_scan(request: Request) -> Any:
        from fastapi.responses import JSONResponse as _JSONResponse

        h = _require_handlers()
        try:
            body = await request.json()
        except Exception:
            return _JSONResponse(
                status_code=422,
                content={"detail": [{"field": "body", "message": "Invalid JSON"}]},
            )
        if not isinstance(body, dict):
            return _JSONResponse(
                status_code=422,
                content={"detail": [{"field": "body", "message": "Expected JSON object"}]},
            )
        text = body.get("text", "")
        if not isinstance(text, str) or not text.strip():
            err = {"field": "text", "message": "Text must be a non-empty string"}
            return _JSONResponse(status_code=422, content={"detail": [err]})
        if len(text) > 100_000:
            err = {"field": "text", "message": "Text exceeds 100000 character limit"}
            return _JSONResponse(status_code=422, content={"detail": [err]})
        direction = body.get("direction", "inbound")
        if not isinstance(direction, str) or direction not in _VALID_DIRECTIONS:
            err = {"field": "direction", "message": "Must be 'inbound' or 'outbound'"}
            return _JSONResponse(status_code=422, content={"detail": [err]})
        session_id = body.get("session_id")
        if session_id is not None and not isinstance(session_id, str):
            err = {"field": "session_id", "message": "Must be a string or null"}
            return _JSONResponse(status_code=422, content={"detail": [err]})
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
        from fastapi.responses import StreamingResponse as _SR

        h = _require_handlers()
        q = h.sse.subscribe()
        return _SR(
            h.sse.stream(q),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/about")
    async def get_about() -> Any:
        return await _require_handlers().get_about()
