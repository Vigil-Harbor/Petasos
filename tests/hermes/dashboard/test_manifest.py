"""The committed dashboard manifest matches the generator."""

from __future__ import annotations

from petasos.hermes.dashboard.manifest import MANIFEST_PATH, render_dashboard_manifest


def test_committed_dashboard_manifest_matches() -> None:
    """Regenerating the dashboard manifest produces the committed file."""
    assert MANIFEST_PATH.read_text(encoding="utf-8") == render_dashboard_manifest()
