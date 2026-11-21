"""Refresh changes the environment without rewriting or enabling the plugin."""

from __future__ import annotations

import argparse
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from petasos.cli import main
from petasos.hermes import host, install
from petasos.hermes.commands import install_registered_cli, run_registered
from petasos.hermes.environment import Probe, Runtime
from petasos.hermes.wheel import wheel_source
from tests.hermes.conftest import enabled_config, healthy_home
from tests.hermes.test_install import _install, _probe

if TYPE_CHECKING:
    from pathlib import Path


def _saved(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    healthy_home(home, monkeypatch)
    target = home / "plugins" / "petasos"
    wheel = target / "wheels" / "new" / "petasos-0.4.0-py3-none-any.whl"
    wheel.parent.mkdir(parents=True)
    wheel.write_bytes(b"new")
    (target / "pyproject.toml").write_text(install.render_project(f"new/{wheel.name}"))
    old = target / "wheels" / "old" / wheel.name
    old.parent.mkdir()
    old.write_bytes(b"old")
    monkeypatch.setattr(install, "runtime_python", lambda home: Runtime(wheel))
    original = host.load_module
    monkeypatch.setattr(
        host,
        "load_module",
        lambda name: SimpleNamespace() if name == "hermes_cli.plugins_cmd" else original(name),
    )
    return wheel


def _snapshot(home: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in home.rglob("*") if path.is_file()}


def _run(home: Path) -> install.InstallResult:
    return install.refresh_plugin(home, home_reason="test", color=False)


@pytest.mark.parametrize("directory", [False, True])
def test_refresh_needs_a_development_wheel(tmp_path: Path, directory: bool) -> None:
    if directory:
        target = tmp_path / "plugins" / "petasos"
        target.mkdir(parents=True)
        (target / "pyproject.toml").write_text('dependencies = ["petasos==0.4.0"]\n')
    before = _snapshot(tmp_path)
    result = _run(tmp_path)
    assert result.exit_code != 0
    assert "development" in result.text and "local" in result.text
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("config", ["plugins: {}\n", enabled_config() + "  disabled: [petasos]\n"])
def test_refresh_never_enables_a_plugin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: str
) -> None:
    _saved(tmp_path, monkeypatch)
    (tmp_path / "config.yaml").write_text(config)
    before = _snapshot(tmp_path)
    result = _run(tmp_path)
    assert result.exit_code != 0
    assert "hermes plugins enable petasos" in result.text
    assert f"HERMES_HOME={tmp_path}" in result.text
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("problem", ["missing-wheel", "broken-config", "no-hermes"])
def test_refresh_preflight_changes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    problem: str,
) -> None:
    wheel = _saved(tmp_path, monkeypatch)
    if problem == "missing-wheel":
        wheel.unlink()
    elif problem == "broken-config":
        (tmp_path / "config.yaml").write_text("plugins: [\n")
    else:
        original = host.load_module
        monkeypatch.setattr(
            host,
            "load_module",
            lambda name: None if name == "hermes_cli.plugins_cmd" else original(name),
        )
    before = _snapshot(tmp_path)
    code = main(["hermes", "refresh", "--home", str(tmp_path)])
    assert code != 0
    output = capsys.readouterr().out
    if problem == "no-hermes":
        assert "not importable" in output and "hermes petasos refresh" in output
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("outcome", ["refused", "stale", "unknown", "success"])
def test_refresh_verifies_before_pruning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    wheel = _saved(tmp_path, monkeypatch)
    old = wheel.parent.parent / "old" / wheel.name
    before = _snapshot(tmp_path)
    calls: list[bool] = []
    current = (
        _probe(wheel)
        if outcome == "success"
        else (Probe(ok=True) if outcome == "unknown" else _probe(old))
    )
    probes = iter([_probe(old), current, current])
    monkeypatch.setattr(install, "probe_petasos", lambda python: next(probes))

    def rebuild(*, repair: bool = False) -> tuple[bool, str]:
        calls.append(repair)
        assert _snapshot(tmp_path) == before
        return outcome != "refused", "Hermes admission result"

    monkeypatch.setattr(install, "republish", rebuild)
    result = _run(tmp_path)
    assert calls == [False]
    if outcome == "success":
        assert result.exit_code == 0
        assert not old.exists() and wheel.exists()
        assert "next time it starts" in result.text
        assert result.report is not None
        assert _snapshot(tmp_path) == {key: value for key, value in before.items() if key != old}
        # A second command verifies the same wheel without another admission.
        again = _run(tmp_path)
        assert again.exit_code == 0 and "already" in again.text
        assert calls == [False]
    else:
        assert result.exit_code != 0
        assert "hermes petasos refresh" in result.text
        # Only a build known to differ is reported as the earlier one.
        assert ("earlier build" in result.text) == (outcome != "unknown")
        assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("repair_needed", [False, True])
def test_refresh_uses_the_shared_import_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repair_needed: bool
) -> None:
    wheel = _saved(tmp_path, monkeypatch)
    probes = iter(
        [Probe(ok=False), Probe(ok=False) if repair_needed else _probe(wheel), _probe(wheel)]
    )
    monkeypatch.setattr(install, "probe_petasos", lambda python: next(probes))
    calls: list[bool] = []

    def rebuild(*, repair: bool = False) -> tuple[bool, str]:
        calls.append(repair)
        return True, "Hermes rebuilt the environment"

    monkeypatch.setattr(install, "republish", rebuild)
    assert _run(tmp_path).exit_code == 0
    assert calls == ([False, True] if repair_needed else [False])


def test_registered_refresh_targets_a_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "profiles" / "ops"
    wheel = _saved(home, monkeypatch)
    monkeypatch.setattr(install, "probe_petasos", lambda python: _probe(wheel))
    parser = argparse.ArgumentParser()
    install_registered_cli(parser)
    args = parser.parse_args(["refresh", "--home", str(tmp_path), "--profile", "ops"])
    assert run_registered(args) == 0


@pytest.mark.parametrize("on", [False, True])
@pytest.mark.parametrize("refused", [False, True])
def test_install_reports_the_profile_state_and_whether_hermes_was_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, on: bool, refused: bool
) -> None:
    home = tmp_path / "home with spaces"
    wheel = _saved(home, monkeypatch)
    old = wheel.parent.parent / "old" / wheel.name
    monkeypatch.setattr(install, "probe_petasos", lambda python: _probe(old))
    monkeypatch.setattr("petasos.hermes.wheel._existing_wheel", lambda: wheel)
    before = (home / "config.yaml").read_bytes()
    if not on:
        before = b"plugins: {}\n"
        (home / "config.yaml").write_bytes(before)
    original = host.load_module
    monkeypatch.setattr(
        host,
        "load_module",
        lambda name: (
            SimpleNamespace(
                dashboard_set_agent_plugin_enabled=lambda *args, **kwargs: {
                    "ok": False,
                    "error": "test refusal",
                }
            )
            if name == "hermes_cli.plugins_cmd" and refused
            else (None if name == "hermes_cli.plugins_cmd" else original(name))
        ),
    )
    result = _install(home)
    assert (home / "config.yaml").read_bytes() == before
    assert wheel_source(wheel.parent.parent.parent / "pyproject.toml") is not None
    assert old.exists()
    if refused:
        assert "test refusal" in result.text
    else:
        assert "not importable" in result.text
    if on:
        assert result.exit_code == 1
        assert "still checking tool calls" in result.text
        assert "tool calls are not checked yet" not in result.text
        assert f"HERMES_HOME='{home}' hermes petasos refresh" in result.text
    else:
        assert result.exit_code == 2
        assert "tool calls are not checked yet" in result.text
        assert f"HERMES_HOME='{home}' hermes plugins enable petasos" in result.text


def test_install_without_hermes_stops_offering_refresh_once_the_build_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    wheel = _saved(home, monkeypatch)
    monkeypatch.setattr("petasos.hermes.wheel._existing_wheel", lambda: wheel)
    original = host.load_module
    monkeypatch.setattr(
        host,
        "load_module",
        lambda name: None if name == "hermes_cli.plugins_cmd" else original(name),
    )
    # The environment already holds these bytes, as it does after a refresh.
    monkeypatch.setattr(install, "probe_petasos", lambda python: _probe(wheel))
    saved = _install(home)
    assert saved.exit_code == 1
    assert "hermes petasos refresh" in saved.text
    again = _install(home)
    assert again.exit_code == 0
    assert "hermes petasos refresh" not in again.text
    assert "not checked" not in again.text


def test_a_plugin_install_just_turned_on_is_not_rebuilt_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    wheel = _saved(home, monkeypatch)
    monkeypatch.setattr("petasos.hermes.wheel._existing_wheel", lambda: wheel)
    monkeypatch.setattr(install, "enable_plugin", lambda: (True, "Hermes turned the plugin on."))
    monkeypatch.setattr(install, "probe_petasos", lambda python: _probe(wheel))

    def unexpected(*, repair: bool = False) -> tuple[bool, str]:
        pytest.fail("Turning the plugin on already admitted these files")

    monkeypatch.setattr(install, "republish", unexpected)
    result = _install(home)
    assert result.exit_code == 0
