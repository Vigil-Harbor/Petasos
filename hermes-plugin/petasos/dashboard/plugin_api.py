"""Hermes loads this module and mounts ``router`` at ``/api/plugins/petasos/``."""

from petasos.hermes.dashboard import build_router

router = build_router()
