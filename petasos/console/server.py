"""FastAPI app factory and route handlers for the Petasos Console."""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from petasos.console._config_meta import generate_config_metadata
from petasos.console._ring_buffer import RingBuffer
from petasos.console._sse import SSEBroadcaster
from petasos.normalize import normalize

if TYPE_CHECKING:
    from petasos.pipeline import Pipeline

_logger = logging.getLogger(__name__)

_MAX_SCAN_TEXT_LEN = 100_000


class ConsoleHandlers:
    """Shared route handlers used by both standalone and Hermes plugin modes."""

    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline
        self.scan_history = RingBuffer[dict[str, Any]](maxlen=500)
        self.sse = SSEBroadcaster()
        self._start_time = time.monotonic()

        pipeline.add_audit_listener(self._on_audit)
        pipeline.add_alert_listener(self._on_alert)

    def _on_audit(self, event: Any) -> None:
        import asyncio

        try:
            data = event.to_dict() if hasattr(event, "to_dict") else {"raw": str(event)}
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.sse.broadcast("audit", data))
        except Exception:
            _logger.debug("Console audit broadcast failed", exc_info=True)

    def _on_alert(self, alert: Any) -> None:
        import asyncio

        try:
            data = alert.to_dict() if hasattr(alert, "to_dict") else {"raw": str(alert)}
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.sse.broadcast("alert", data))
        except Exception:
            _logger.debug("Console alert broadcast failed", exc_info=True)

    async def get_config(self) -> dict[str, Any]:
        config_dict = self.pipeline.config.to_dict(redact_secrets=True)
        fields = generate_config_metadata()
        return {"config": config_dict, "fields": fields}

    async def update_config(self, body: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, str]] | None]:
        current = self.pipeline.config.to_dict()
        current.pop("session_secret", None)
        merged = {**current, **body}
        try:
            from petasos.config import PetasosConfig

            PetasosConfig.from_dict(merged)
        except (ValueError, TypeError) as exc:
            msg = str(exc)
            field = _extract_field_from_error(msg, body)
            return None, [{"field": field, "message": msg}]
        return {"config": merged, "fields": generate_config_metadata()}, None

    async def run_scan(self, text: str, direction: str = "inbound", session_id: str | None = None) -> dict[str, Any]:
        result = await self.pipeline.inspect(text, direction=direction, session_id=session_id)

        cfg = self.pipeline.config
        normalized_text = normalize(
            text,
            nfkc=cfg.normalize_nfkc,
            strip_zero_width=cfg.strip_zero_width,
            map_homoglyphs=cfg.map_homoglyphs,
            detect_rtl=cfg.detect_rtl_override,
        ).normalized

        scan_id = f"s-{uuid.uuid4().hex[:6]}"
        summary = {
            "scan_id": scan_id,
            "safe": result.safe,
            "finding_count": len(result.findings),
            "duration_ms": sum(
                (sr.duration_ms or 0.0) for sr in result.scanner_results
            ),
            "direction": direction,
            "timestamp": time.time(),
        }
        self.scan_history.push(summary)
        await self.sse.broadcast("scan_result", summary)

        return {
            "result": result.to_dict(),
            "normalized_text": normalized_text,
            "scan_id": scan_id,
        }

    async def get_health(self) -> dict[str, Any]:
        cfg = self.pipeline.config
        config_hash = hashlib.sha256(
            json.dumps(cfg.to_dict(redact_secrets=True), sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

        return {
            "pipeline": {
                "fail_mode": cfg.fail_mode,
                "scanner_count": len(self.pipeline.scanner_health()),
                "config_hash": config_hash,
                "uptime_seconds": round(time.monotonic() - self._start_time, 1),
            },
            "scanners": self.pipeline.scanner_health(),
            "feature_status": dict(self.pipeline._build_feature_status()),
        }

    async def get_scan_history(self, limit: int = 100) -> dict[str, Any]:
        clamped = min(max(1, limit), 1000)
        return {"entries": list(reversed(self.scan_history.to_list(clamped)))}

    async def get_profiles(self) -> dict[str, Any]:
        return {"profiles": self.pipeline.list_profiles()}

    async def get_about(self) -> dict[str, Any]:
        import petasos

        return {
            "version": getattr(petasos, "__version__", "0.1.0"),
            "repo_url": "https://github.com/Vigil-Harbor/Petasos",
            "license": "MIT",
            "description": "Pluggable, session-aware content security pipeline for Python AI agents",
            "donation": {
                "message": "Did Petasos prevent a disaster? Every feature is free, forever. If this saved your team from a bad day, a coffee keeps the lights on.",
                "url": "https://github.com/sponsors/Vigil-Harbor",
            },
            "credits": ["Vigil Harbor — maintainer", "Built with FastAPI, Python, vanilla JS"],
        }


def _extract_field_from_error(msg: str, body: dict[str, Any]) -> str:
    for key in body:
        if key in msg:
            return key
    return "unknown"


def build_app(pipeline: Pipeline) -> FastAPI:
    """Build the complete FastAPI application."""
    import importlib.resources

    app = FastAPI(title="Petasos Console", version="0.1.0")
    handlers = ConsoleHandlers(pipeline)

    static_dir = importlib.resources.files("petasos.console") / "static"

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        handlers.sse.shutdown()

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        html_path = static_dir / "index.html"
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/config")
    async def api_get_config() -> dict[str, Any]:
        return await handlers.get_config()

    @app.put("/api/config")
    async def api_update_config(request: Request) -> Any:
        from fastapi.responses import JSONResponse

        body = await request.json()
        result, errors = await handlers.update_config(body)
        if errors is not None:
            return JSONResponse(status_code=422, content={"detail": errors})
        return result

    @app.post("/api/scan")
    async def api_run_scan(request: Request) -> Any:
        from fastapi.responses import JSONResponse

        body = await request.json()
        text = body.get("text", "")
        if not text or not text.strip():
            return JSONResponse(status_code=422, content={"detail": [{"field": "text", "message": "Text must not be empty"}]})
        if len(text) > _MAX_SCAN_TEXT_LEN:
            return JSONResponse(status_code=422, content={"detail": [{"field": "text", "message": f"Text exceeds {_MAX_SCAN_TEXT_LEN} character limit"}]})
        direction = body.get("direction", "inbound")
        session_id = body.get("session_id")
        return await handlers.run_scan(text, direction=direction, session_id=session_id)

    @app.get("/api/health")
    async def api_get_health() -> dict[str, Any]:
        return await handlers.get_health()

    @app.get("/api/scan-history")
    async def api_get_scan_history(limit: int = 100) -> dict[str, Any]:
        return await handlers.get_scan_history(limit)

    @app.get("/api/profiles")
    async def api_get_profiles() -> dict[str, Any]:
        return await handlers.get_profiles()

    @app.get("/api/events")
    async def api_events() -> StreamingResponse:
        q = handlers.sse.subscribe()
        return StreamingResponse(
            handlers.sse.stream(q),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/about")
    async def api_get_about() -> dict[str, Any]:
        return await handlers.get_about()

    return app
