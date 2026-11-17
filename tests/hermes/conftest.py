"""Homes and a Hermes stand-in for the command tests.

Every home is a temporary directory. Nothing here reads a real Hermes install.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from petasos.hermes.doctor import Check, HermesView
from petasos.hermes.install import dashboard_texts, render_project
from petasos.hermes.manifest import render_manifest

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def write_plugin(home: Path) -> Path:
    """Write the three plugin files this Petasos would write."""
    target = home / "plugins" / "petasos"
    target.mkdir(parents=True, exist_ok=True)
    (target / "plugin.yaml").write_text(render_manifest(), encoding="utf-8")
    (target / "__init__.py").write_text(
        "from petasos.hermes.plugin import register\n",
        encoding="utf-8",
    )
    (target / "pyproject.toml").write_text(
        render_project("petasos-0.4.0-py3-none-any.whl"), encoding="utf-8"
    )
    dashboard = target / "dashboard"
    dashboard.mkdir(parents=True, exist_ok=True)
    for name, text in dashboard_texts().items():
        (dashboard / name).write_text(text, encoding="utf-8")
    return target


def write_config(home: Path, body: str) -> Path:
    """Write ``config.yaml`` exactly as ``body``."""
    path = home / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def enabled_config(*, role: str = "general", level: str = "balanced", extra: str = "") -> str:
    """A config that turns Petasos on and stores the four settings."""
    return (
        "plugins:\n"
        "  enabled:\n"
        "    - petasos\n"
        "  entries:\n"
        "    petasos:\n"
        "      settings:\n"
        f"        enabled: true\n"
        f"        role: {role}\n"
        f"        level: {level}\n"
        "        overrides: {}\n"
        f"{extra}"
    )


def patch_hermes_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Report a new enough Hermes, and a plugin load Hermes accepted."""

    def view() -> HermesView:
        return HermesView(
            status="ok",
            summary="Hermes 0.23.1 is new enough for this plugin.",
            version="0.23.1",
        )

    def loaded(plugin_dir: Path) -> Check:
        del plugin_dir
        return Check(
            id="plugin_load",
            status="ok",
            summary="Hermes accepted the plugin files.",
        )

    monkeypatch.setattr("petasos.hermes.doctor.hermes_view", view)
    monkeypatch.setattr("petasos.hermes.doctor.plugin_load_view", loaded)


def healthy_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A profile whose files and settings are the usual ones, with Hermes patched in."""
    write_plugin(tmp_path)
    write_config(tmp_path, enabled_config())
    patch_hermes_ok(monkeypatch)
    return tmp_path


def approval_grant(**flags: bool) -> Any:
    """An approval probe result. Unset flags are false."""
    from petasos.enforce.types import ApprovalGrant

    return ApprovalGrant(
        mode_off=flags.get("mode_off", False),
        yolo=flags.get("yolo", False),
        context=flags.get("context", False),
    )
