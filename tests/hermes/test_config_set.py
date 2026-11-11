"""``petasos config set`` and ``hermes petasos config set`` refuse Required Semgrep."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from petasos.cli import main
from petasos.hermes.commands import install_registered_cli, run_registered
from tests.hermes.conftest import write_plugin

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


_REQUIRED = (
    '        overrides:\n          scanners:\n            semgrep:\n              enabled: "on"\n'
)


def _home(tmp_path: Path, overrides: str = "") -> None:
    write_plugin(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "plugins:\n"
        "  enabled:\n"
        "    - petasos\n"
        "  entries:\n"
        "    petasos:\n"
        "      settings:\n"
        "        enabled: true\n"
        "        role: general\n"
        "        level: balanced\n"
        f"{overrides}",
        encoding="utf-8",
    )


def _remember(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def remember(values: dict[str, Any], *, plugin_dir: Path) -> None:
        calls.append({"values": dict(values), "plugin_dir": plugin_dir})

    monkeypatch.setattr("petasos.hermes.config_set.write_settings", remember)
    return calls


def test_set_required_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Setting Semgrep to Required does not call Hermes's writer."""
    _home(tmp_path)
    calls = _remember(monkeypatch)
    code = main(["config", "set", "scanners.semgrep.enabled", "on", "--home", str(tmp_path)])
    out = capsys.readouterr().out

    assert code == 2
    assert calls == []
    assert "cannot be set to Required" in out
    assert "on" not in (tmp_path / "config.yaml").read_text(encoding="utf-8")


def test_set_something_else_while_required_is_stored_names_the_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Leaving Required in place while changing another setting is refused."""
    _home(tmp_path, _REQUIRED)
    before = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    calls = _remember(monkeypatch)
    code = main(["config", "set", "level", "strict", "--home", str(tmp_path)])
    out = capsys.readouterr().out

    assert code == 2
    assert calls == []
    assert "petasos config set scanners.semgrep.enabled off" in out
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == before


def test_set_off_is_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The command the doctor prints does turn Required off."""
    _home(tmp_path, _REQUIRED)
    calls = _remember(monkeypatch)
    code = main(["config", "set", "scanners.semgrep.enabled", "off", "--home", str(tmp_path)])
    out = capsys.readouterr().out

    assert code == 0
    assert out == "Saved.\n"
    assert calls[0]["values"]["overrides"]["scanners"]["semgrep"]["enabled"] == "off"
    assert calls[0]["plugin_dir"] == tmp_path / "plugins" / "petasos"


def test_registered_set_refuses_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``hermes petasos config set`` uses the same refusal."""
    _home(tmp_path)
    calls = _remember(monkeypatch)
    parser = argparse.ArgumentParser(prog="hermes")
    sub = parser.add_subparsers(dest="command")
    target = sub.add_parser("petasos")
    install_registered_cli(target)
    args = parser.parse_args(
        [
            "petasos",
            "config",
            "set",
            "scanners.semgrep.enabled",
            "on",
            "--home",
            str(tmp_path),
        ]
    )
    code = run_registered(args)
    out = capsys.readouterr().out

    assert code == 2
    assert calls == []
    assert "cannot be set to Required" in out
