"""The dashboard manifest Hermes discovers next to the plugin.

The committed ``dashboard/manifest.json`` is this text. A test fails when
the file drifts. The later install command copies the dashboard directory,
or writes this text again, into the profile's plugin directory.
"""

from __future__ import annotations

import json
from pathlib import Path

from petasos.hermes.manifest import DESCRIPTION, release_version
from petasos.hermes.settings import PLUGIN_ID

DASHBOARD_DIR = Path(__file__).resolve().parents[3] / "hermes-plugin" / "petasos" / "dashboard"
MANIFEST_PATH = DASHBOARD_DIR / "manifest.json"
_PACKAGED_TAB = Path(__file__).resolve().parents[1] / "tab_files"


def tab_source() -> Path | None:
    """The directory that holds the built tab, or None when this copy has none.

    A checkout has it in the plugin directory. An installed wheel carries a copy.
    """
    for candidate in (DASHBOARD_DIR, _PACKAGED_TAB):
        if (candidate / "index.js").is_file():
            return candidate
    return None


def dashboard_manifest() -> dict[str, object]:
    """The manifest object. ``name`` is the plugin id Hermes mounts under."""
    return {
        "name": PLUGIN_ID,
        "label": "Petasos",
        "description": DESCRIPTION,
        "icon": "Shield",
        "version": release_version(),
        "tab": {"path": "/petasos", "position": "after:skills"},
        "entry": "index.js",
        "api": "plugin_api.py",
    }


def render_dashboard_manifest() -> str:
    """The manifest file text, with a trailing newline."""
    return json.dumps(dashboard_manifest(), indent=2) + "\n"


def write_dashboard_manifest(path: Path | None = None) -> Path:
    """Write the manifest and return the path."""
    target = MANIFEST_PATH if path is None else path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_dashboard_manifest(), encoding="utf-8")
    return target
