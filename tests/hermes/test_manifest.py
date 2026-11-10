"""The committed plugin manifest is what the library would generate."""

from __future__ import annotations

from pathlib import Path

from petasos.hermes.manifest import render_manifest

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
    assert 'dependencies = ["petasos>=0.4,<0.5"]' in project
