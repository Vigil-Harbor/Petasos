"""The scanner command names a scanner, and says what happens next."""

from __future__ import annotations

from typing import TYPE_CHECKING

from petasos.cli import main
from petasos.hermes import semgrep_host

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _project(home: Path, requirement: str = "petasos==0.4.0") -> Path:
    plugin = home / "plugins" / "petasos"
    plugin.mkdir(parents=True)
    path = plugin / "pyproject.toml"
    path.write_text(
        "[project]\n"
        'name = "petasos-hermes-plugin"\n'
        'version = "0.4.0"\n'
        f'dependencies = ["{requirement}"]\n'
        "\n"
        "[tool.uv.sources]\n"
        'petasos = { path = "wheels/petasos.whl" }\n',
        encoding="utf-8",
    )
    return path


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(argv)
    return code, capsys.readouterr().out


def test_an_unknown_name_is_rejected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A package specifier is not a scanner name, and the answer lists the names."""
    code, out = _run(["scanner", "add", "petasos[prompt-guard]", "--home", str(tmp_path)], capsys)
    assert code == 2
    assert "no scanner named" in out
    assert "prompt_guard" in out
    assert "presidio" in out
    assert "semgrep" in out


def test_add_names_the_scanner_and_the_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Adding PromptGuard edits the dependency list and says what happens next."""
    project = _project(tmp_path)
    monkeypatch.setattr(
        "petasos.hermes.scanners_cmd.republish",
        lambda: (True, "Hermes rebuilt the environment a new process runs."),
    )
    code, out = _run(["scanner", "add", "prompt_guard", "--home", str(tmp_path)], capsys)
    text = project.read_text(encoding="utf-8")
    assert "petasos[prompt-guard]==0.4.0" in text
    assert 'path = "wheels/petasos.whl"' in text
    assert "PromptGuard" in out
    assert "Restart Hermes" in out
    assert "1.1 GB" in out
    assert "Hugging Face" in out
    assert code == 0


def test_add_without_hermes_still_edits_the_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The dependency list changes even when this Python cannot ask Hermes to rebuild."""
    project = _project(tmp_path)
    code, out = _run(["scanner", "add", "presidio", "--home", str(tmp_path)], capsys)
    assert "petasos[presidio]==0.4.0" in project.read_text(encoding="utf-8")
    assert code == 2
    assert "not available" in out
    assert "was not" in out


def test_remove_drops_the_extra(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Removing a scanner takes its extra off the requirement and keeps the pin."""
    project = _project(tmp_path, "petasos[prompt-guard]==0.4.0")
    code, out = _run(["scanner", "remove", "PromptGuard", "--home", str(tmp_path)], capsys)
    text = project.read_text(encoding="utf-8")
    assert "petasos==0.4.0" in text
    assert "prompt-guard" not in text
    assert "removed" in out
    assert code == 2


def test_add_semgrep_is_refused_inside_hermes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Semgrep cannot run inside Hermes, so add does not change the dependency list."""
    project = _project(tmp_path)
    before = project.read_text(encoding="utf-8")
    code, out = _run(["scanner", "add", "semgrep", "--home", str(tmp_path)], capsys)

    assert code == 2
    assert out == (
        "Semgrep cannot run inside Hermes yet, so it was not added. It would not check any code.\n"
    )
    assert "risky code" not in out
    assert project.read_text(encoding="utf-8") == before


def test_remove_semgrep_still_drops_the_extra(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Removing Semgrep still edits the dependency list."""
    project = _project(tmp_path, "petasos[semgrep]==0.4.0")
    code, out = _run(["scanner", "remove", "semgrep", "--home", str(tmp_path)], capsys)
    text = project.read_text(encoding="utf-8")

    assert "petasos==0.4.0" in text
    assert "semgrep" not in text
    assert "removed" in out
    assert code == 2


def test_add_semgrep_is_allowed_when_hermes_can_run_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one fact, patched true, lets add name Semgrep in the dependency list."""
    project = _project(tmp_path)
    monkeypatch.setattr(semgrep_host, "semgrep_can_run", lambda: True)
    monkeypatch.setattr(
        "petasos.hermes.scanners_cmd.republish",
        lambda: (True, "Hermes rebuilt the environment a new process runs."),
    )
    code, out = _run(["scanner", "add", "semgrep", "--home", str(tmp_path)], capsys)

    assert code == 0
    assert "petasos[semgrep]==0.4.0" in project.read_text(encoding="utf-8")
    assert "Restart Hermes" in out


def test_add_without_a_plugin_names_install(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """There is nothing to edit until the plugin is installed."""
    code, out = _run(["scanner", "add", "presidio", "--home", str(tmp_path)], capsys)
    assert code == 2
    assert "not installed" in out
    assert f"petasos hermes install --home {tmp_path}" in out


def test_install_output_names_the_development_route(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A dry run says this is the development install and names the wheel."""
    code, out = _run(["hermes", "install", "--home", str(tmp_path), "--dry-run"], capsys)
    assert code == 0
    assert "development install" in out
    assert "petasos-0.4.0-py3-none-any.whl" in out
    assert "released" in out
    assert "Dry run" in out
