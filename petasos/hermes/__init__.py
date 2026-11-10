"""Hermes host adapter.

The console and the guard still import ``petasos.hermes.home`` for path
resolution. Hook registration is ``petasos.hermes.plugin.register``.
"""

from petasos.hermes.manifest import (
    plugin_requirement,
    release_version,
    render_manifest,
    render_plugin_project,
)
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
    "plugin_requirement",
    "protected_paths",
    "register",
    "release_version",
    "render_manifest",
    "render_plugin_project",
    "write_settings",
]
