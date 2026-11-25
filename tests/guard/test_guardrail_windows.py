"""Windows spellings of a protected path and of a program name.

Hermes runs its Windows terminal and file tools through Git Bash. See
docs/architecture/hermes-host-facts.md, section 19.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from petasos.guard import shell
from petasos.guard.guardrail import recognize
from petasos.guard.paths import _native_drive, _owned
from petasos.guard.shell import _heredoc_hit
from petasos.guard.shell_parse import _parse, _program, _Simple, _spelled
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


@pytest.mark.parametrize(
    ("command", "argv", "redirects"),
    [
        ("rm C:/x/hermes/conf\\ig.yaml", ("rm", "C:/x/hermes/config.yaml"), ()),
        ("echo x > C:/x/hermes/conf\\ig.yaml", ("echo", "x"), ("C:/x/hermes/config.yaml",)),
        ("rm C:/x/herm\\es/config.yaml", ("rm", "C:/x/hermes/config.yaml"), ()),
        ("rm -r C:/x/hermes/plugins/pet\\asos", ("rm", "-r", "C:/x/hermes/plugins/petasos"), ()),
        ("C:\\Tools\\hermes.exe x", ("C:Toolshermes.exe", "x"), ()),
    ],
)
def test_a_drive_letter_word_is_read_as_the_shell_reads_it(
    command: str, argv: tuple[str, ...], redirects: tuple[str, ...]
) -> None:
    """The shell drops an unquoted backslash in a drive-letter word too, on every host.

    The Windows-path spelling keeps the backslash. It is an extra check that
    can only add a match; the shell's reading is the command.
    """
    [(shell_command, spelled)] = _spelled(command)
    assert (shell_command.argv, shell_command.redirects) == (argv, redirects)
    assert spelled is not None
    assert any(BACKSLASH in word for word in (*spelled.argv, *spelled.redirects))


@pytest.mark.parametrize(
    "native",
    [
        "C:\\Users\\x\\.hermes\\config.yaml",
        "C:\\x\\hermes\\nested\\..\\config.yaml",
        "C:\\x\\_cache\\-old\\~tmp\\$name\\config.yaml",
        "C:\\x\\hermes\\*.yaml",
    ],
)
def test_the_spelling_keeps_every_separator_of_a_native_path(native: str) -> None:
    """A folder name need not start with a letter: ``.hermes`` is Hermes's own home."""
    [(_shell_command, spelled)] = _spelled(f"rm {native}")
    assert spelled is not None
    assert spelled.argv == ("rm", native)


@pytest.mark.parametrize("char", list(" \t\n'\"\\;|&()`<>"))
def test_a_spelling_reads_an_escaped_shell_character_as_the_shell_does(char: str) -> None:
    """Escaped, each of these is part of the word, so the command does not end there.

    A spelling that took the backslash for a separator would read the
    character after it as the shell's own, and hold other commands or words
    than the shell's reading does.
    """
    [(command, spelled), (after, after_spelled)] = _spelled(f"rm C:\\x\\{char}y; echo ok")
    assert after.argv == ("echo", "ok")
    assert after_spelled is None
    assert spelled is not None
    # The one difference is the separator kept after the drive.
    assert spelled.argv == ("rm", command.argv[1].replace("C:x", "C:\\x", 1))
    assert spelled.redirects == command.redirects == ()


def test_only_a_command_with_a_drive_letter_word_has_a_spelling() -> None:
    assert _spelled("rm hermes/conf\\ig.yaml")[0][1] is None
    assert _spelled("rm C:/x/hermes/config.yaml")[0][1] is None
    spellings = [d is None for _, d in _spelled("rm C:/x/conf\\ig.yaml; echo ok")]
    assert spellings == [False, True]


@windows_only
def test_a_reading_that_adds_python_keeps_the_other_interpreter_check(tmp_path: Path) -> None:
    """The shell's reading runs perl's check on the document. The Windows-path
    reading adds Python, whose check skips comments; it must not replace perl's.

    Called directly: on the terminal tool the document's lines are also read
    as shell commands, which already name this path.
    """
    home = tmp_path / "hermes"
    home.mkdir()
    config = home / "config.yaml"
    config.write_text("plugins: {}\n", encoding="utf-8")
    surface = hermes_surface([str(config)], roots=(str(home),))
    owned = _owned((str(config),), surface, ())
    text = f"perl -e 1; C:\\Tools\\python.exe <<EOF\n# '{config.as_posix()}'\nEOF"
    hit = _heredoc_hit(text, owned, surface, {"HOME": str(tmp_path)}, str(tmp_path))
    assert hit is not None
    assert hit.kind == "settings"


def test_a_spelling_adds_no_nested_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A spelling is checked for what it names, not for what it runs.

    Both levels hold a drive-letter word. With a second reading of each whole
    text, each ending in its own directory, the inner ``echo ok`` was judged
    four times.
    """
    judged: list[tuple[str, ...]] = []
    original = shell._one_command

    def counting(command: _Simple, *args: object, **kwargs: object) -> GuardrailHit | None:
        judged.append(command.argv)
        return original(command, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(shell, "_one_command", counting)
    command = "cd C:a\\b; python -c \"import os; os.system('cd C:c\\\\d; echo ok')\""
    assert _recognize(tmp_path, "terminal", {"command": command}) is None
    assert judged.count(("echo", "ok")) == 1


@pytest.mark.parametrize(
    "code",
    [
        "import subprocess; "
        'subprocess.run(["C:\\Tools\\hermes.exe", "plugins", "disable", "petasos"])',
        'import os; os.system("C:\\Tools\\hermes.exe plugins disable petasos")',
    ],
)
def test_program_text_keeps_a_native_program_path(tmp_path: Path, code: str) -> None:
    """Python hands an argument list, or cmd a line, to Windows without Git Bash.

    ``\\T`` and ``\\h`` are not Python escapes, so the program text holds
    single backslashes.
    """
    hit = _recognize(tmp_path, "execute_code", {"code": code})
    assert hit is not None
    assert hit.kind == "plugin"


@pytest.mark.parametrize(
    "program",
    ["C:\\Tools\\hermes.exe", "C:/Tools/hermes.exe", "C:\\Tools\\hermes", "C:/Tools/hermes"],
)
def test_a_drive_path_program_is_recognised(tmp_path: Path, program: str) -> None:
    hit = _recognize(tmp_path, "terminal", {"command": f"{program} plugins disable petasos"})
    assert hit is not None
    assert hit.kind == "plugin"


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
        # Git Bash drops these backslashes, so the file is not removed. The
        # Windows-path reading still names the config, and that only adds an ask.
        "rm {native}",
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
    ("tail", "named"),
    [
        ("config.yaml", "config.yaml"),
        ("plugins\\..\\config.yaml", "config.yaml"),
        (".\\config.yaml", "config.yaml"),
        ("*.yaml", "*.yaml"),
    ],
)
def test_an_unquoted_native_path_under_a_dot_folder_names_the_config(
    tmp_path: Path, tail: str, named: str
) -> None:
    """Hermes's home is ``.hermes``, and a native path may step through ``..``.

    Git Bash drops these backslashes, so the file is not touched. The
    Windows-path reading still names the config, and that only adds an ask.
    The hit reports the path the command named, or the wildcard that covers it.
    """
    home = tmp_path / ".hermes"
    (home / "plugins").mkdir(parents=True)
    config = home / "config.yaml"
    config.write_text("plugins: {}\n", encoding="utf-8")
    surface = hermes_surface([str(config)], roots=(str(home),))
    command = f"rm {home}{BACKSLASH}{tail}"
    hit = recognize(
        "terminal",
        {"command": command},
        surface=surface,
        package=(),
        environ={"HOME": str(tmp_path)},
        cwd=str(tmp_path),
    )
    assert hit is not None, command
    assert hit.kind == "settings"
    assert hit.target == os.path.normcase(home.resolve() / named)


@windows_only
@pytest.mark.parametrize(
    ("command", "kind"),
    [
        ("rm {home}/conf\\ig.yaml", "settings"),
        ("echo x > {home}/conf\\ig.yaml", "settings"),
        ("rm {root}/herm\\es/config.yaml", "settings"),
        ("rm -r {home}/plugins/pet\\asos", None),
    ],
)
def test_a_backslash_inside_a_drive_path_still_names_the_file(
    tmp_path: Path, command: str, kind: str | None
) -> None:
    """Git Bash drops the backslash, so each of these reaches the real file."""
    text = command.format(
        home=(tmp_path / "hermes").as_posix(),
        root=tmp_path.as_posix(),
    )
    hit = _recognize(tmp_path, "terminal", {"command": text})
    assert hit is not None, text
    if kind is not None:
        assert hit.kind == kind


@windows_only
@pytest.mark.parametrize(
    "template",
    [
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

    absolute = f"{_bash_form(home)}/{climb}{config.lstrip('/')}"
    again = _recognize(tmp_path, "terminal", {"command": f"rm {absolute}"}, environ={})
    assert again is not None


@windows_only
@pytest.mark.parametrize("cwd_form", ["bash", "native"])
@pytest.mark.parametrize(
    "template",
    ["rm {name}", "python -c \"open('{name}', 'w').write('x')\""],
)
def test_dots_that_stop_at_the_drive_as_a_native_program_reads_them(
    tmp_path: Path, cwd_form: str, template: str
) -> None:
    """Windows stops ``..`` at the drive: ``../../Users/x`` from ``C:/a/b`` is ``C:/Users/x``."""
    home = tmp_path / "hermes"
    below_drive = (home / "config.yaml").as_posix()[3:]
    climb = "../" * (len(_bash_form(home).strip("/").split("/")) - 1)
    hit = _recognize(
        tmp_path,
        "terminal",
        {"command": template.format(name=climb + below_drive)},
        cwd=_bash_form(home) if cwd_form == "bash" else str(home),
        environ={},
    )
    assert hit is not None
    assert hit.kind == "settings"


@pytest.mark.skipif(os.name == "nt", reason="a drive letter is part of the path on Windows")
def test_a_drive_letter_does_not_hide_a_path_in_program_text_off_windows(tmp_path: Path) -> None:
    config = (tmp_path / "hermes" / "config.yaml").as_posix()
    hit = _recognize(tmp_path, "terminal", {"command": f"sed 'w C:{config}' /tmp/input"})
    assert hit is not None
    assert hit.kind == "settings"


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
