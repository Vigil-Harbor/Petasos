"""Petasos Console — operations dashboard for the content security pipeline.

Dual-mode: works as a Hermes Desktop plugin (primary) or standalone
via a local FastAPI server.

Usage (standalone)::

    from petasos import Pipeline
    from petasos.console import serve

    pipeline = Pipeline(...)
    serve(pipeline, port=8384)  # http://127.0.0.1:8384
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from petasos.pipeline import Pipeline

__all__ = ["create_app", "serve"]


def create_app(pipeline: Pipeline) -> "FastAPI":  # type: ignore[name-defined]  # noqa: F821
    """Build a FastAPI app wired to *pipeline* for the console dashboard."""
    from petasos.console.server import build_app

    return build_app(pipeline)


def serve(pipeline: Pipeline, *, port: int = 8384) -> None:
    """Start the standalone console server on 127.0.0.1:*port*."""
    import uvicorn

    app = create_app(pipeline)
    uvicorn.run(app, host="127.0.0.1", port=port)
