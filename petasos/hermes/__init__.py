"""Hermes host adapter.

The console and the guard still import ``petasos.hermes.home`` for path
resolution. Hook registration is ``petasos.hermes.plugin.register``.
"""

from petasos.hermes.manifest import render_manifest
from petasos.hermes.plugin import (
    close,
    directive,
    host_info,
    protected_paths,
    register,
)
from petasos.hermes.settings import PLUGIN_ID, HermesSettings, write_settings

__all__ = [
    "PLUGIN_ID",
    "HermesSettings",
    "close",
    "directive",
    "host_info",
    "protected_paths",
    "register",
    "render_manifest",
    "write_settings",
]
