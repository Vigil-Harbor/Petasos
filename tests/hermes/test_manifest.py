"""The committed plugin manifest is what the library would generate."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

import petasos

if TYPE_CHECKING:
    import pytest

from petasos.hermes.manifest import render_manifest, render_plugin_project

_ROOT = Path(__file__).resolve().parents[2]
_PLUGIN = _ROOT / "hermes-plugin" / "petasos"
_FORBIDDEN = (
    "MemoryProvider",
    "CronScheduler",
    "ComputerUseProvider",
    "register_memory_provider",
    "register_cron_scheduler",
    "register_computer_use_provider",
)


def test_committed_manifest_matches_the_generator() -> None:
    """Regenerating plugin.yaml produces the committed file."""
    committed = (_PLUGIN / "plugin.yaml").read_text(encoding="utf-8")
    assert committed == render_manifest()


def test_committed_project_matches_the_generator() -> None:
    """The directory version and the wheel range come from the package version."""
    committed = (_PLUGIN / "pyproject.toml").read_text(encoding="utf-8")
    assert committed == render_plugin_project()


def test_plugin_directory_is_one_import() -> None:
    """The directory carries no logic, and its text does not mark it exclusive."""
    source = (_PLUGIN / "__init__.py").read_text(encoding="utf-8")
    imports = [
        line
        for line in source.splitlines()
        if line.startswith("from ") or line.startswith("import ")
    ]
    assert imports == ["from petasos.hermes.plugin import register"]
    for word in _FORBIDDEN:
        assert word not in source
    project = (_PLUGIN / "pyproject.toml").read_text(encoding="utf-8")
    assert project == render_plugin_project()


def test_generated_versions_and_wheel_range_follow_the_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(petasos, "__version__", "7.8.9")
    manifest = yaml.safe_load(render_manifest())
    project = tomllib.loads(render_plugin_project())["project"]
    assert manifest["version"] == project["version"] == "7.8.9"
    assert project["dependencies"] == ["petasos>=7.8,<7.9"]
