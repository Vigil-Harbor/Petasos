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
    from fastapi import FastAPI

    from petasos.pipeline import Pipeline

__all__ = ["create_app", "serve"]

_shared_pipeline: Pipeline | None = None


def create_app(pipeline: Pipeline, *, auth_token: str | None = None) -> FastAPI:
    """Build a FastAPI app wired to *pipeline* for the console dashboard.

    *auth_token* is forwarded verbatim to ``build_app``, which performs the
    normalization, validation, and the set-but-blank WARNING (PET-125). A plain
    stringized annotation here (this module keeps ``from __future__ import
    annotations``); no FastAPI annotation resolution is involved.
    """
    from petasos.console.server import build_app

    return build_app(pipeline, auth_token=auth_token)


def serve(pipeline: Pipeline, *, port: int = 8384, auth_token: str | None = None) -> None:
    """Start the standalone console server on 127.0.0.1:*port*.

    PET-125: when *auth_token* is None, the token is resolved from the
    ``PETASOS_CONSOLE_TOKEN`` environment variable (unset returns None, so auth
    stays off; a set-but-blank value makes ``build_app`` log one WARNING and run
    without auth). An explicit non-None *auth_token* argument overrides the
    environment (test seam).
    """
    import os

    import uvicorn

    if auth_token is None:
        auth_token = os.environ.get("PETASOS_CONSOLE_TOKEN")
    app = create_app(pipeline, auth_token=auth_token)
    uvicorn.run(app, host="127.0.0.1", port=port)
