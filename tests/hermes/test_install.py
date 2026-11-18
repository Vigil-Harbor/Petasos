"""The install command writes the plugin files, and does not write config.yaml itself."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from petasos.cli import main
from petasos.hermes import install
from petasos.hermes import wheel as wheel_module
from petasos.hermes.dashboard import manifest as tab_manifest
from petasos.hermes.dashboard.manifest import render_dashboard_manifest
from petasos.hermes.environment import Probe, Runtime
from petasos.hermes.install import RELEASED_COMMAND, dashboard_texts, render_project
from petasos.hermes.manifest import render_manifest
from petasos.hermes.wheel import wheel_source

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _wheel_already_built(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Give install a wheel file to place, so no test here needs the uv build tool."""
    source = tmp_path_factory.mktemp("built") / wheel_module.wheel_filename()
    source.write_bytes(b"stand-in wheel")
    monkeypatch.setattr(wheel_module, "_existing_wheel", lambda: source)


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
    target = tmp_path / "plugins" / "petasos"
    wheel = wheel_source(target / "pyproject.toml")
    assert wheel is not None and wheel.is_file()
    assert written["pyproject.toml"] == render_project(
        wheel.relative_to(target / "wheels").as_posix()
    )
    assert "MemoryProvider" not in written["__init__.py"]
    dashboard = tmp_path / "plugins" / "petasos" / "dashboard"
    shipped = dashboard_texts()
    for name, text in shipped.items():
        assert (dashboard / name).read_text(encoding="utf-8") == text
    assert (dashboard / "manifest.json").read_text(encoding="utf-8") == render_dashboard_manifest()
    watched = {
        "wheel": wheel,
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


@pytest.mark.parametrize("success", [False, True])
def test_refresh_keeps_old_wheels_until_admission_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, success: bool
) -> None:
    """Admission sees both immutable builds; cleanup follows only success."""
    source = tmp_path / "build.whl"
    source.write_bytes(b"old")
    monkeypatch.setattr(wheel_module, "_existing_wheel", lambda: source)
    monkeypatch.setattr(install, "enable_plugin", lambda: (True, "Hermes turned the plugin on."))
    home = tmp_path / "home"
    _install(home)
    directory = home / "plugins" / "petasos" / "wheels"
    old = next(directory.glob("*/*.whl"))
    legacy = directory / old.name
    legacy.write_bytes(b"legacy")
    source.write_bytes(b"new")
    monkeypatch.setattr(
        install, "enable_plugin", lambda: (True, "Hermes already had the plugin turned on.")
    )
    calls: list[bool] = []

    def rebuild(*, repair: bool = False) -> tuple[bool, str]:
        calls.append(repair)
        assert old.read_bytes() == b"old"
        assert legacy.read_bytes() == b"legacy"
        assert len(list(directory.glob("*/*.whl"))) == 2
        return success, "admission result"

    monkeypatch.setattr(install, "runtime_python", lambda home: Runtime(source))
    probes = iter([_probe(old), _probe(source)])
    monkeypatch.setattr(install, "probe_petasos", lambda python: next(probes))
    monkeypatch.setattr(install, "republish", rebuild)
    result = _install(home)
    assert calls == [False]
    assert old.exists() is not success
    assert legacy.exists() is not success
    current = wheel_source(directory.parent / "pyproject.toml")
    assert current is not None and current.read_bytes() == b"new"
    if not success:
        assert result.exit_code != 0
        assert "hermes petasos refresh" in result.text


def test_unchanged_build_does_not_rebuild(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "build.whl"
    source.write_bytes(b"same")
    monkeypatch.setattr(wheel_module, "_existing_wheel", lambda: source)
    monkeypatch.setattr(install, "enable_plugin", lambda: (True, "Hermes turned the plugin on."))
    _install(tmp_path / "home")
    monkeypatch.setattr(
        install, "enable_plugin", lambda: (True, "Hermes already had the plugin turned on.")
    )
    monkeypatch.setattr(install, "runtime_python", lambda home: Runtime(source))
    monkeypatch.setattr(install, "probe_petasos", lambda python: _probe(source))

    def unexpected(*, repair: bool = False) -> tuple[bool, str]:
        pytest.fail("An unchanged, working install must not rebuild")

    monkeypatch.setattr(install, "republish", unexpected)
    _install(tmp_path / "home")


@pytest.mark.parametrize("normal_fixes_import", [False, True])
def test_a_broken_import_tries_pending_sources_before_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, normal_fixes_import: bool
) -> None:
    """An unchanged file may still be pending after a failed admission."""
    source = tmp_path / "build.whl"
    source.write_bytes(b"pending")
    monkeypatch.setattr(wheel_module, "_existing_wheel", lambda: source)
    monkeypatch.setattr(install, "enable_plugin", lambda: (False, "admission failed"))
    home = tmp_path / "home"
    _install(home)
    monkeypatch.setattr(
        install, "enable_plugin", lambda: (True, "Hermes already had the plugin turned on.")
    )
    monkeypatch.setattr(install, "runtime_python", lambda home: Runtime(source))
    probes = iter(
        [
            Probe(ok=False),
            _probe(source) if normal_fixes_import else Probe(ok=False),
            _probe(source),
        ]
    )
    monkeypatch.setattr(install, "probe_petasos", lambda python: next(probes))
    calls: list[bool] = []

    def rebuild(*, repair: bool = False) -> tuple[bool, str]:
        calls.append(repair)
        return True, "rebuilt"

    monkeypatch.setattr(install, "republish", rebuild)
    _install(home)
    assert calls == ([False] if normal_fixes_import else [False, True])


def _install(home: Path) -> install.InstallResult:
    return install.install_plugin(
        home,
        home_reason="test",
        dry_run=False,
        force=False,
        released=False,
        run=False,
        color=False,
    )


def _probe(source: Path) -> Probe:
    return Probe(ok=True, version="0.4.0", direct_url=json.dumps({"url": source.as_uri()}))


def test_reinstall_keeps_added_scanners_and_removal_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from petasos.hermes.dependencies import petasos_requirement
    from petasos.hermes.scanners_cmd import change_scanner

    source = tmp_path / "build.whl"
    source.write_bytes(b"same")
    monkeypatch.setattr(wheel_module, "_existing_wheel", lambda: source)
    monkeypatch.setattr("petasos.hermes.scanners_cmd.republish", lambda: (True, "Rebuilt."))
    home = tmp_path / "profile"
    _install(home)
    project = home / "plugins" / "petasos" / "pyproject.toml"
    for name in ("presidio", "prompt_guard"):
        assert change_scanner(home, name, present=True)[1] == 0
    _install(home)
    requirement = petasos_requirement(project)
    assert requirement is not None
    assert set(requirement[0]) == {"presidio", "prompt-guard"}
    assert change_scanner(home, "presidio", present=False)[1] == 0
    _install(home)
    requirement = petasos_requirement(project)
    assert requirement is not None
    assert requirement[0] == ("prompt-guard",)
