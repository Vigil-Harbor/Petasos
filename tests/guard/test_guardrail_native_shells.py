"""A script handed to PowerShell or cmd as one argument is read with that shell's rules.

Hermes runs Windows terminal commands through Git Bash, and from there an
agent can start ``powershell -Command "..."`` or ``cmd /c "..."``. See
docs/architecture/hermes-host-facts.md, section 19.
"""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING

import pytest

from petasos.guard.guardrail import recognize
from petasos.guard.native_shell import _native_parse, _native_script
from petasos.hermes.guardrail import hermes_surface

if TYPE_CHECKING:
    from pathlib import Path

    from petasos.guard.surface import GuardrailHit

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows path forms")
BACKSLASH = "\\"


def _recognize(tmp_path: Path, command: str) -> GuardrailHit | None:
    home = tmp_path / "hermes"
    (home / "plugins" / "petasos").mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("plugins: {}\n", encoding="utf-8")
    package = tmp_path / "pkg" / "petasos"
    package.mkdir(parents=True, exist_ok=True)
    paths = [home / "config.yaml", home / "plugins" / "petasos"]
    surface = hermes_surface((str(path) for path in paths), roots=(str(home),))
    return recognize(
        "terminal",
        {"command": command},
        protected=(str(home / "config.yaml"),),
        surface=surface,
        package=(str(package),),
        environ={"HERMES_HOME": str(home), "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)},
        cwd=str(tmp_path),
    )


def _command(tmp_path: Path, template: str) -> str:
    config = tmp_path / "hermes" / "config.yaml"
    return template.format(
        config=config.as_posix(),
        native=str(config),
        share=BACKSLASH * 2 + "localhost" + BACKSLASH + str(config)[0] + "$" + str(config)[2:],
    )


CHANGES = [
    # The examples from the ticket, with forward slashes.
    "powershell -Command \"Remove-Item '{config}'\"",
    'powershell -Command "Remove-Item {config}"',
    'powershell -c "Set-Content -Path {config} -Value x"',
    'powershell -NoProfile -Command "Remove-Item {config}"',
    'powershell.exe -NoProfile -Command "Remove-Item {config}"',
    "pwsh -c 'Remove-Item {config}'",
    'cmd //c "del {config}"',
    'cmd.exe /c "echo x > {config}"',
    'cmd //c "copy nul {config}"',
    # Prefixes and letter case of the switches.
    'powershell -co "Remove-Item {config}"',
    'powershell -com "Remove-Item {config}"',
    'powershell -COMMAND "Remove-Item {config}"',
    'powershell //command "Remove-Item {config}"',
    'powershell -ExecutionPolicy Bypass -WindowStyle Hidden -c "Remove-Item {config}"',
    'cmd //C "del {config}"',
    'cmd /K "del {config}"',
    'cmd //r "del {config}"',
    'cmd //q //d //c "del {config}"',
    "cmd //cdel {config}",
    # Windows PowerShell runs the first word that is not an option as a command.
    'powershell -NoProfile "Remove-Item {config}"',
    # Quoting.
    "powershell -c 'Remove-Item \"{config}\"'",
    "powershell -c 'Remove-Item -Path:{config}'",
    "powershell -c 'Remove-Item /tmp/x,{config}'",
    "powershell -c 'Remove-Item {config} # a comment'",
    'cmd //c "del ""{config}"""',
    'cmd //c "del,{config}"',
    # Separators.
    "powershell -c 'Get-Content /tmp/x; Remove-Item {config}'",
    "powershell -c 'Get-Content /tmp/x\nRemove-Item {config}'",
    "powershell -c 'Get-Content /tmp/x && Remove-Item {config}'",
    "powershell -c 'Test-Path /tmp/x || Remove-Item {config}'",
    "powershell -c 'Get-Content /tmp/x | Set-Content {config}'",
    'cmd //c "type /tmp/x & del {config}"',
    'cmd //c "type /tmp/x && del {config}"',
    'cmd //c "type /tmp/x || del {config}"',
    'cmd //c "type /tmp/x | del {config}"',
    'cmd //c "(del {config})"',
    # A redirect inside the script, whatever the program.
    "powershell -c 'Write-Output x > {config}'",
    "powershell -c 'Get-Content /tmp/x >> {config}'",
    "powershell -c 'Write-Output x *> {config}'",
    'cmd //c "type nul > {config}"',
    'cmd //c "echo x 2> {config}"',
    # A reader whose result goes on to a writer, or whose result is used.
    "powershell -c 'Get-Item {config} | Remove-Item'",
    "powershell -c '(Get-Item {config}).Delete()'",
    "powershell -c 'Get-ChildItem {config} | ForEach-Object {{ $_.Delete() }}'",
    # An unknown program with a protected path among its operands.
    'powershell -c \'[IO.File]::WriteAllText("{config}", "x")\'',
    "pwsh Remove-Item {config}",
    # A script inside a script.
    'bash -c "powershell -c \\"Remove-Item {config}\\""',
    'powershell -c "cmd //c del {config}"',
    'cmd //c "powershell -c Remove-Item {config}"',
    "powershell -c \"Invoke-Expression 'Remove-Item {config}'\"",
    "powershell -c \"iex 'Remove-Item {config}'\"",
    'timeout 5 powershell -c "Remove-Item {config}"',
    # Environment forms. Bash would expand $env in double quotes, so these use single quotes.
    "powershell -c 'Remove-Item $env:HERMES_HOME/config.yaml'",
    "powershell -c 'Remove-Item ${{env:hermes_home}}/config.yaml'",
    "powershell -c 'Remove-Item \"$env:HERMES_HOME/config.yaml\"'",
    "powershell -c 'Remove-Item $HOME/hermes/config.yaml'",
    "powershell -c 'Remove-Item ~/hermes/config.yaml'",
    'cmd //c "del %HERMES_HOME%/config.yaml"',
    'cmd //c "del %hermes_home%/config.yaml"',
    'cmd //c "del %USERPROFILE%/hermes/config.yaml"',
]


@pytest.mark.parametrize("template", CHANGES)
def test_a_script_given_to_a_native_shell_changes_the_config(
    tmp_path: Path, template: str
) -> None:
    command = _command(tmp_path, template)
    hit = _recognize(tmp_path, command)
    assert hit is not None, command
    assert hit.kind == "settings"


@pytest.mark.parametrize(
    "command",
    [
        'powershell -c "hermes plugins disable petasos"',
        "powershell -c '& hermes plugins disable petasos'",
        'cmd //c "hermes plugins disable petasos"',
        "pwsh -Command 'Write-Output x; hermes plugins disable petasos'",
    ],
)
def test_a_hermes_command_inside_a_native_script(tmp_path: Path, command: str) -> None:
    hit = _recognize(tmp_path, command)
    assert hit is not None, command
    assert hit.kind == "plugin"


READS = [
    'powershell -Command "Get-Content {config}"',
    "powershell Get-Content {config}",
    "powershell -c 'gc {config} | Select-String plugins'",
    "powershell -c 'Get-Item {config} | Format-List'",
    "powershell -c 'Test-Path {config}; Get-Content /tmp/x'",
    'cmd //c "type {config}"',
    'cmd //c "findstr plugins {config}"',
    'cmd //c "type {config} | more"',
    'cmd //c "dir {config}"',
    # Text that only mentions the path.
    "powershell -c 'Write-Output {config}'",
    "powershell -c \"Write-Output '{config}' > /tmp/notes.txt\"",
    'cmd //c "echo {config} > /tmp/notes.txt"',
    # A path elsewhere.
    "powershell -c 'Remove-Item /tmp/petasos-not-here.txt'",
    'cmd //c "del /tmp/petasos-not-here.txt"',
    # A comment is not read.
    "powershell -c 'Write-Output x # Remove-Item {config}'",
]


@pytest.mark.parametrize("template", READS)
def test_a_native_script_that_leaves_the_config_alone(tmp_path: Path, template: str) -> None:
    command = _command(tmp_path, template)
    assert _recognize(tmp_path, command) is None, command


@pytest.mark.parametrize(
    "command",
    [
        "gc {config}",
        "gi {config}",
        "sls x {config}",
        "type {config}",
        "dir {config}",
        "findstr x {config}",
        "where {config}",
    ],
)
def test_native_reader_names_are_other_programs_in_bash(tmp_path: Path, command: str) -> None:
    """Outside a PowerShell or cmd script these names get no reader's exemption."""
    hit = _recognize(tmp_path, _command(tmp_path, command))
    assert hit is not None
    assert hit.kind == "settings"


@pytest.mark.parametrize("switch", ["-EncodedCommand", "-enc", "-e", "-ec"])
def test_an_encoded_command_is_not_read(tmp_path: Path, switch: str) -> None:
    """A documented limit: the base64 text is left unread."""
    script = _command(tmp_path, "Remove-Item {config}")
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    assert _recognize(tmp_path, f"powershell {switch} {encoded}") is None


@pytest.mark.parametrize(
    ("argv", "script"),
    [
        (("powershell", "-c", "a", "b"), "a b"),
        (("powershell", "-Co", "a"), "a"),
        (("powershell", "/Command", "a"), "a"),
        (("powershell", "–Command", "a"), "a"),
        (("powershell", "-NoProfile", "a", "-c", "b"), "a -c b"),
        (("powershell", "-ep", "Bypass", "a"), "a"),
        (("powershell", "-ExecutionPolicy", "Bypass", "-c", "a"), "a"),
        (("powershell", "-File", "x.ps1", "a"), None),
        (("powershell", "-f", "x.ps1"), None),
        (("powershell", "-EncodedCommand", "AAAA"), None),
        (("powershell", "-Command", "-"), "-"),
        (("powershell", "-"), None),
        (("powershell", "-NoProfile"), None),
        (("pwsh", "a.ps1", "b"), None),
        (("pwsh", "-c", "a"), "a"),
        (("pwsh", "-cwa", "a", "b"), "a"),
        (("cmd", "/c", "a", "b"), "a b"),
        (("cmd", "//C", "a"), "a"),
        (("cmd", "/k", "a"), "a"),
        (("cmd", "/cdel", "x"), "del x"),
        (("cmd", "/q", "/c", "a"), "a"),
        (("cmd", "a"), None),
        (("cmd", "-c", "a"), None),
    ],
)
def test_the_script_a_native_shell_is_handed(argv: tuple[str, ...], script: str | None) -> None:
    shell = "cmd" if argv[0] == "cmd" else argv[0]
    assert _native_script(shell, argv) == script


def _argvs(text: str, shell: str, env: dict[str, str] | None = None) -> list[tuple[str, ...]]:
    return [
        command.argv
        for pipeline in _native_parse(text, shell, env or {})
        for command, _ in pipeline
    ]


def test_powershell_quoting() -> None:
    path = "C:" + BACKSLASH + "H" + BACKSLASH + "config.yaml"
    assert _argvs(f"Remove-Item '{path}'", "powershell") == [("Remove-Item", path)]
    assert _argvs(f"Remove-Item {path}", "powershell") == [("Remove-Item", path)]
    assert _argvs('a \'it\'\'s\' "q""q" "a`tb" c`onfig', "powershell") == [
        ("a", "it's", 'q"q', "a\tb", "config")
    ]
    assert _argvs("a ‘x’ “y”", "powershell") == [("a", "x", "y")]
    assert _argvs("a -Path:x b,c", "powershell") == [("a", "-Path:", "x", "b", "c")]
    assert _argvs("a # b c\nd", "powershell") == [("a",), ("d",)]


def test_powershell_environment_forms() -> None:
    env = {"HERMES_HOME": "/h", "USERPROFILE": "/u"}
    text = "a $env:HERMES_HOME/x \"${env:hermes_home}/y\" '$env:HERMES_HOME' $HOME/z ~/w $env:NOPE"
    assert _argvs(text, "powershell", env) == [
        ("a", "/h/x", "/h/y", "$env:HERMES_HOME", "/u/z", "/u/w", "$env:NOPE")
    ]


def test_cmd_quoting_and_environment() -> None:
    path = "C:" + BACKSLASH + "H" + BACKSLASH + "config.yaml"
    env = {"HERMES_HOME": "/h"}
    assert _argvs(f'del "{path}"', "cmd") == [("del", path)]
    assert _argvs("@del a^&b x,y;z=w", "cmd") == [("del", "a&b", "x", "y", "z", "w")]
    assert _argvs('echo "a^b" %hermes_home% %NOPE%', "cmd", env) == [
        ("echo", "a^b", "/h", "%NOPE%")
    ]


@pytest.mark.parametrize(
    ("text", "shell", "expected"),
    [
        (
            "a; b\nc | d && e || f & g",
            "powershell",
            [["a"], ["b"], ["c", "d"], ["e"], ["f"], ["g"]],
        ),
        ("a & b\nc | d && e || f", "cmd", [["a"], ["b"], ["c", "d"], ["e"], ["f"]]),
        # In cmd a semicolon separates words, not commands.
        ("a;b", "cmd", [["a b"]]),
    ],
)
def test_separators(text: str, shell: str, expected: list[list[str]]) -> None:
    pipelines = _native_parse(text, shell, {})
    assert [
        [" ".join(command.argv) for command, _ in pipeline] for pipeline in pipelines
    ] == expected


def test_redirects() -> None:
    parsed = _native_parse("a x > f1; b 2>> f2; c *> f3", "powershell", {})
    assert [
        (command.argv, command.redirects) for pipeline in parsed for command, _ in pipeline
    ] == [
        (("a", "x"), ("f1",)),
        (("b",), ("f2",)),
        (("c",), ("f3",)),
    ]


@windows_only
@pytest.mark.parametrize(
    "template",
    [
        "powershell -Command \"Remove-Item '{native}'\"",
        'powershell -Command "Remove-Item {native}"',
        'powershell -c "Set-Content -Path {native} -Value x"',
        "pwsh -c 'Remove-Item {native}'",
        'cmd //c "del {native}"',
        'cmd.exe /c "echo x > {native}"',
        'cmd //c "copy nul {native}"',
        "powershell -c 'Remove-Item $env:HERMES_HOME\\config.yaml'",
        "powershell -c 'Remove-Item ~\\hermes\\config.yaml'",
        'cmd //c "del %HERMES_HOME%\\config.yaml"',
        'cmd //c "del %USERPROFILE%\\hermes\\config.yaml"',
        "powershell -c 'Remove-Item {share}'",
    ],
)
def test_a_native_script_names_the_config_with_backslashes(tmp_path: Path, template: str) -> None:
    command = _command(tmp_path, template)
    hit = _recognize(tmp_path, command)
    assert hit is not None, command
    assert hit.kind == "settings"


@windows_only
@pytest.mark.parametrize(
    "template",
    [
        'powershell -Command "Get-Content {native}"',
        'cmd //c "type {native}"',
        "powershell Get-Content {config}",
    ],
)
def test_a_native_script_reads_the_config_with_backslashes(tmp_path: Path, template: str) -> None:
    command = _command(tmp_path, template)
    assert _recognize(tmp_path, command) is None, command


@windows_only
@pytest.mark.parametrize(
    "spelled",
    [
        "{bs}{bs}localhost{bs}{drive}${rest}",
        "{bs}{bs}127.0.0.1{bs}{lower}${rest}",
        "//LOCALHOST/{drive}${fwd}",
        "{bs}{bs}?{bs}UNC{bs}localhost{bs}{drive}${rest}",
    ],
)
def test_an_administrative_share_on_this_machine_is_the_drive(
    tmp_path: Path, spelled: str
) -> None:
    config = str(tmp_path / "hermes" / "config.yaml")
    path = spelled.format(
        bs=BACKSLASH,
        drive=config[0],
        lower=config[0].lower(),
        rest=config[2:],
        fwd=config[2:].replace(BACKSLASH, "/"),
    )
    home = tmp_path / "hermes"
    (home / "plugins" / "petasos").mkdir(parents=True, exist_ok=True)
    surface = hermes_surface((config,), roots=(str(home),))
    hit = recognize(
        "write_file",
        {"path": path, "content": "x"},
        protected=(config,),
        surface=surface,
        package=(str(tmp_path / "pkg"),),
        environ={},
        cwd=str(tmp_path),
    )
    assert hit is not None, path
    assert hit.kind == "settings"
