"""Question 1: a directory plugin that fronts a wheel."""

from __future__ import annotations

from pathlib import Path

from tests.hermes_host.client import invoke
from tests.hermes_host.marks import requires_hermes_sandbox

pytestmark = requires_hermes_sandbox

STANDIN = Path(__file__).resolve().parent / "standin" / "plugin"


def test_validate_fails_until_the_wheel_imports(hermes_sandbox: Path, tmp_path: Path) -> None:
    plugin = tmp_path / "missing-wheel"
    plugin.mkdir()
    (plugin / "plugin.yaml").write_text(
        'name: missing-wheel\nversion: "0.1.0"\ndescription: "import fails"\n',
        encoding="utf-8",
    )
    (plugin / "__init__.py").write_text(
        "from standin_hostfacts_absent import register\n",
        encoding="utf-8",
    )
    (plugin / "pyproject.toml").write_text(
        '[project]\nname = "missing-wheel"\nversion = "0.1.0"\n'
        'description = "missing"\nrequires-python = ">=3.11"\ndependencies = []\n',
        encoding="utf-8",
    )
    report = invoke(hermes_sandbox, {"action": "validate", "path": str(plugin)})
    assert report["ok"] is False
    checks = {item["name"]: item for item in report["report"]["checks"]}
    assert checks["capability probe"]["ok"] is False
    assert "standin_hostfacts_absent" in checks["capability probe"]["detail"]


def test_directory_plugin_validates_and_loads(hermes_sandbox: Path) -> None:
    report = invoke(hermes_sandbox, {"action": "validate", "path": str(STANDIN)})
    assert report["ok"] is True, report
    kind = invoke(hermes_sandbox, {"action": "parse_kind", "path": str(STANDIN)})
    assert kind["kind"] == "standalone"
    loaded = invoke(hermes_sandbox, {"action": "load_state"})
    plugin = loaded["plugins"]["standin-hostfacts"]
    assert plugin["enabled"] is True
    assert plugin["error"] is None
    assert plugin["kind"] == "standalone"
    assert "pre_tool_call" in plugin["hooks"]
    assert "transform_tool_result" in plugin["hooks"]


def test_memory_provider_marker_in_init_changes_kind(hermes_sandbox: Path, tmp_path: Path) -> None:
    plugin = tmp_path / "kind-bait"
    plugin.mkdir()
    (plugin / "plugin.yaml").write_text(
        'name: kind-bait\nversion: "0.1.0"\ndescription: "kind bait"\n',
        encoding="utf-8",
    )
    (plugin / "__init__.py").write_text(
        "from standin_hostfacts.plugin import register\n# MemoryProvider\n",
        encoding="utf-8",
    )
    kind = invoke(hermes_sandbox, {"action": "parse_kind", "path": str(plugin)})
    assert kind["kind"] == "exclusive"
