"""Windows spellings of a protected path and of a program name.

Hermes runs its Windows terminal and file tools through Git Bash. See
docs/architecture/hermes-host-facts.md, section 19.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from petasos.guard.guardrail import recognize
from petasos.guard.paths import _native_drive
from petasos.guard.shell_parse import _parse, _program
from petasos.hermes.guardrail import hermes_surface

if TYPE_CHECKING:
    from pathlib import Path

    from petasos.guard.surface import GuardrailHit

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows path forms")
BACKSLASH = "\\"


def _recognize(
    tmp_path: Path,
    tool: str,
    params: dict[str, object],
    *,
    cwd: str | None = None,
    environ: dict[str, str] | None = None,
) -> GuardrailHit | None:
    home = tmp_path / "hermes"
    (home / "plugins" / "petasos").mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("plugins: {}\n", encoding="utf-8")
    package = tmp_path / "pkg" / "petasos"
    package.mkdir(parents=True, exist_ok=True)
    paths = [home / "config.yaml", home / "plugins" / "petasos"]
    surface = hermes_surface((str(path) for path in paths), roots=(str(home),))
    return recognize(
        tool,
        params,
        protected=(str(home / "config.yaml"),),
        surface=surface,
        package=(str(package),),
        environ={"HERMES_HOME": str(home), "HOME": str(tmp_path)} if environ is None else environ,
        cwd=str(tmp_path) if cwd is None else cwd,
    )


def _bash_form(path: Path) -> str:
    """``C:\\Users\\x`` as Git Bash writes it: ``/c/Users/x``."""
    forward = str(path).replace(BACKSLASH, "/")
    return "/" + forward[0].lower() + forward[2:]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/c/Users/x/config.yaml", "c:/Users/x/config.yaml"),
        ("/C/Users/x", "C:/Users/x"),
        ("/c", "c:/"),
        ("/cygdrive/d/x", "d:/x"),
        ("/mnt/c/x", "c:/x"),
        ("/home/x/config.yaml", "/home/x/config.yaml"),
        ("/cc/x", "/cc/x"),
        ("c/x", "c/x"),
        ("C:/Users/x", "C:/Users/x"),
    ],
)
def test_a_bash_drive_directory_is_the_drive(text: str, expected: str) -> None:
    assert _native_drive(text) == expected


def test_double_quotes_keep_a_backslash_before_an_ordinary_character() -> None:
    """As a shell does: only a few characters are escaped inside double quotes."""
    native = "C:" + BACKSLASH + "Users" + BACKSLASH + "x"
    assert _parse(f'rm "{native}"')[0].argv == ("rm", native)
    doubled = native.replace(BACKSLASH, BACKSLASH * 2)
    assert _parse(f'rm "{doubled}"')[0].argv == ("rm", native)
    assert _parse('echo "a' + BACKSLASH + '"b"')[0].argv == ("echo", 'a"b')
    assert _parse('echo "' + BACKSLASH + '$HOME"')[0].argv == ("echo", "$HOME")


@windows_only
@pytest.mark.parametrize("name", ["hermes.exe", "HERMES.EXE", "hermes.cmd", "hermes.bat"])
def test_an_executable_suffix_is_the_same_program(name: str) -> None:
    assert _program(name) == "hermes"


@pytest.mark.skipif(os.name == "nt", reason="the suffix names the same program on Windows")
@pytest.mark.parametrize("command", ["cat.exe {config}", "echo.bat {config}", "cp.com {config} x"])
def test_a_suffixed_name_is_another_program_off_windows(tmp_path: Path, command: str) -> None:
    """Off Windows ``cat.exe`` is not ``cat``, so it gets no reader's exemption."""
    config = (tmp_path / "hermes" / "config.yaml").as_posix()
    hit = _recognize(tmp_path, "terminal", {"command": command.format(config=config)})
    assert hit is not None
    assert hit.kind == "settings"


@windows_only
@pytest.mark.parametrize(
    "command",
    [
        "hermes.exe plugins disable petasos",
        "/c/Users/x/venv/Scripts/hermes.exe plugins disable petasos",
        "bash.exe -c 'hermes plugins disable petasos'",
    ],
)
def test_a_program_named_with_its_suffix_is_still_recognised(tmp_path: Path, command: str) -> None:
    hit = _recognize(tmp_path, "terminal", {"command": command})
    assert hit is not None
    assert hit.kind == "plugin"


@windows_only
@pytest.mark.parametrize(
    "template",
    [
        "rm {bash}",
        "rm {upper}",
        "rm /cygdrive{bash}",
        "rm /mnt{bash}",
        'rm "{native}"',
        "rm '{native}'",
        "rm {escaped}",
        "echo x > {bash}",
        "sed -i s/a/b/ {bash}",
        "cat > {bash} <<EOF\nx\nEOF",
        "cp /tmp/x {bash}",
        "echo x | tee {bash}",
        "cd {home} && rm config.yaml",
        "rm -rf {home}",
        "mv {home} {home}2",
        "rm {home}/*.yaml",
        "bash.exe -c 'rm {bash}'",
        "python -c \"open('{bash}', 'w').write('')\"",
    ],
)
def test_a_git_bash_command_names_the_config(tmp_path: Path, template: str) -> None:
    config = tmp_path / "hermes" / "config.yaml"
    command = template.format(
        bash=_bash_form(config),
        upper=_bash_form(config).upper(),
        native=str(config),
        escaped=str(config).replace(BACKSLASH, BACKSLASH * 2),
        home=_bash_form(tmp_path / "hermes"),
    )
    hit = _recognize(tmp_path, "terminal", {"command": command})
    assert hit is not None, command
    assert hit.kind == "settings"


@windows_only
@pytest.mark.parametrize(
    "template",
    [
        # The shell removes an unquoted backslash, so this names no real file.
        "rm {native}",
        "rm /c/Windows/Temp/petasos-not-here.txt",
        "rm /home/x/config.yaml",
        "cat {bash}",
        "cat.exe {bash}",
    ],
)
def test_a_git_bash_command_that_leaves_the_config_alone(tmp_path: Path, template: str) -> None:
    config = tmp_path / "hermes" / "config.yaml"
    command = template.format(bash=_bash_form(config), native=str(config))
    assert _recognize(tmp_path, "terminal", {"command": command}) is None


@windows_only
@pytest.mark.parametrize(
    "form",
    ["bash", "mixed", "long", "long_forward", "device", "trailing_dot", "stream"],
)
def test_a_file_tool_path_names_the_config(tmp_path: Path, form: str) -> None:
    config = tmp_path / "hermes" / "config.yaml"
    native = str(config)
    spelled = {
        "bash": _bash_form(config),
        "mixed": _bash_form(tmp_path) + BACKSLASH + "hermes" + BACKSLASH + "config.yaml",
        "long": BACKSLASH * 2 + "?" + BACKSLASH + native,
        "long_forward": "//?/" + native.replace(BACKSLASH, "/"),
        "device": BACKSLASH * 2 + "." + BACKSLASH + native,
        "trailing_dot": native + ".",
        "stream": native + "::$DATA",
    }[form]
    hit = _recognize(tmp_path, "write_file", {"path": spelled, "content": "x"})
    assert hit is not None, spelled
    assert hit.kind == "settings"


@windows_only
def test_a_relative_name_under_a_git_bash_working_directory(tmp_path: Path) -> None:
    """Hermes reports the working directory the way ``pwd`` prints it.

    The environment is empty so only the working directory can supply the hit.
    """
    hit = _recognize(
        tmp_path,
        "terminal",
        {"command": "rm config.yaml"},
        cwd=_bash_form(tmp_path / "hermes"),
        environ={},
    )
    assert hit is not None
    assert hit.kind == "settings"


@windows_only
@pytest.mark.parametrize("cwd_form", ["bash", "native"])
def test_dots_that_climb_out_of_the_drive_directory(tmp_path: Path, cwd_form: str) -> None:
    """In Git Bash ``..`` from ``/c/x`` reaches ``/``, where ``c`` is the drive again."""
    home = tmp_path / "hermes"
    config = _bash_form(home / "config.yaml")
    climb = "../" * len(_bash_form(home).strip("/").split("/"))
    hit = _recognize(
        tmp_path,
        "terminal",
        {"command": f"rm {climb}{config.lstrip('/')}"},
        cwd=_bash_form(home) if cwd_form == "bash" else str(home),
        environ={},
    )
    assert hit is not None
    assert hit.kind == "settings"

    absolute = f"{_bash_form(home)}/plugins/../config.yaml"
    again = _recognize(tmp_path, "terminal", {"command": f"rm {absolute}"}, environ={})
    assert again is not None


@windows_only
def test_a_sibling_reached_with_dots_is_not_the_config(tmp_path: Path) -> None:
    hit = _recognize(
        tmp_path,
        "terminal",
        {"command": "rm ../notes.txt"},
        cwd=_bash_form(tmp_path / "hermes" / "plugins"),
        environ={},
    )
    assert hit is None
