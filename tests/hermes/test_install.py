"""The install command writes the plugin files, and does not write config.yaml itself."""

from __future__ import annotations

from typing import TYPE_CHECKING

from petasos.cli import main
from petasos.hermes.dashboard import manifest as tab_manifest
from petasos.hermes.dashboard.manifest import render_dashboard_manifest
from petasos.hermes.install import RELEASED_COMMAND, dashboard_texts, render_project
from petasos.hermes.manifest import render_manifest

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(argv)
    return code, capsys.readouterr().out


def _files(home: Path) -> dict[str, str]:
    target = home / "plugins" / "petasos"
    return {
        name: (target / name).read_text(encoding="utf-8")
        for name in ("plugin.yaml", "__init__.py", "pyproject.toml")
    }


def test_dry_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A dry run shows the files and the package-manager warning, and creates nothing."""
    code, out = _run(["hermes", "install", "--home", str(tmp_path), "--dry-run"], capsys)

    assert code == 0
    assert "Dry run. Nothing was written." in out
    assert "development install" in out
    assert "published package" in out
    assert "petasos hermes install --released" in out
    assert not (tmp_path / "plugins" / "petasos").exists()
    assert not (tmp_path / "config.yaml").exists()


def test_install_is_idempotent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The second run finds the same files and does not rewrite them."""
    first, out = _run(["hermes", "install", "--home", str(tmp_path)], capsys)
    assert "Wrote the plugin files." in out
    assert "does not edit Hermes's config file" in out or "not turned on" in out
    assert f"Next: HERMES_HOME={tmp_path} hermes plugins enable petasos" in out
    written = _files(tmp_path)
    assert written["plugin.yaml"] == render_manifest()
    assert written["__init__.py"] == "from petasos.hermes.plugin import register\n"
    assert written["pyproject.toml"] == render_project()
    assert "MemoryProvider" not in written["__init__.py"]
    dashboard = tmp_path / "plugins" / "petasos" / "dashboard"
    shipped = dashboard_texts()
    for name, text in shipped.items():
        assert (dashboard / name).read_text(encoding="utf-8") == text
    assert (dashboard / "manifest.json").read_text(encoding="utf-8") == render_dashboard_manifest()
    watched = {
        **{name: tmp_path / "plugins" / "petasos" / name for name in written},
        **{f"dashboard/{name}": dashboard / name for name in shipped},
    }
    stamps = {name: path.stat().st_mtime_ns for name, path in watched.items()}

    second, again = _run(["hermes", "install", "--home", str(tmp_path)], capsys)
    assert "already match this version" in again
    assert _files(tmp_path) == written
    assert {name: path.stat().st_mtime_ns for name, path in watched.items()} == stamps
    assert not (tmp_path / "config.yaml").exists()
    assert first == second


def test_refuses_to_replace_another_plugin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A directory that is not Petasos is left untouched unless --force is given."""
    target = tmp_path / "plugins" / "petasos"
    target.mkdir(parents=True)
    original = "name: other\nversion: '1'\ndescription: not ours\n"
    (target / "plugin.yaml").write_text(original, encoding="utf-8")
    (target / "keep.txt").write_text("leave me\n", encoding="utf-8")

    code, out = _run(["hermes", "install", "--home", str(tmp_path)], capsys)
    assert code == 2
    assert "Nothing was replaced" in out
    assert "--force" in out
    assert (target / "plugin.yaml").read_text(encoding="utf-8") == original
    assert (target / "keep.txt").read_text(encoding="utf-8") == "leave me\n"

    forced, forced_out = _run(["hermes", "install", "--home", str(tmp_path), "--force"], capsys)
    assert "Wrote the plugin files." in forced_out
    assert (target / "plugin.yaml").read_text(encoding="utf-8") == render_manifest()
    assert (target / "keep.txt").read_text(encoding="utf-8") == "leave me\n"
    assert forced in {0, 1, 2}


def test_released_route_prints_hermes_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The released route prints Hermes's command and does not write files."""
    code, out = _run(["hermes", "install", "--home", str(tmp_path), "--released"], capsys)

    assert code == 0
    assert RELEASED_COMMAND in out
    assert "Nothing was run" in out
    assert not (tmp_path / "plugins").exists()


def test_run_without_released_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--run is only the released installer."""
    code = main(["hermes", "install", "--home", str(tmp_path), "--run"])
    err = capsys.readouterr().err
    assert code == 2
    assert "--released" in err
    assert not (tmp_path / "plugins").exists()


def test_install_then_doctor_names_the_missing_switch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without Hermes, install writes the files and doctor says the plugin is off."""
    code, out = _run(["hermes", "install", "--home", str(tmp_path)], capsys)

    assert "Not protected." in out
    assert "not turned on in Hermes" in out
    assert code == 2

    _code, report = _run(["doctor", "--home", str(tmp_path)], capsys)
    assert f"Next: HERMES_HOME={tmp_path} hermes plugins enable petasos" in report
    assert "Next: petasos hermes install" not in report


def test_a_copy_without_a_checkout_installs_the_tab_it_carries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An installed wheel has no plugin directory beside it; the tab comes from the wheel."""
    carried = tmp_path / "carried"
    carried.mkdir()
    (carried / "index.js").write_text("// tab\n", encoding="utf-8")
    (carried / "plugin_api.py").write_text("router = None\n", encoding="utf-8")
    monkeypatch.setattr(tab_manifest, "DASHBOARD_DIR", tmp_path / "no-checkout")
    monkeypatch.setattr(tab_manifest, "_PACKAGED_TAB", carried)
    home = tmp_path / "home"

    _run(["hermes", "install", "--home", str(home)], capsys)

    dashboard = home / "plugins" / "petasos" / "dashboard"
    assert (dashboard / "index.js").read_text(encoding="utf-8") == "// tab\n"
    assert (dashboard / "plugin_api.py").read_text(encoding="utf-8") == "router = None\n"
    assert (dashboard / "manifest.json").read_text(encoding="utf-8") == render_dashboard_manifest()


def test_a_copy_with_no_tab_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without the tab's files the install stops in words and leaves the home alone."""
    monkeypatch.setattr(tab_manifest, "DASHBOARD_DIR", tmp_path / "no-checkout")
    monkeypatch.setattr(tab_manifest, "_PACKAGED_TAB", tmp_path / "no-wheel-copy")
    home = tmp_path / "home"

    code, out = _run(["hermes", "install", "--home", str(home)], capsys)

    assert code == 2
    assert "Nothing was written" in out
    assert not (home / "plugins").exists()
