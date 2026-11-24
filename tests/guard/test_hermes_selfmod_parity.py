"""The 0.5.0 guard's Hermes configuration-writer cases, against the redesign guard.

Each command case of the 0.5.0 ``tests/test_hermes_selfmod.py`` is driven
through ``ToolCallGuard`` with the real Hermes surface. Every command 0.5.0
flags must be flagged here too. Two commands 0.5.0 leaves alone are flagged
here on purpose; those cases say so. The reference-plugin cases are covered
by ``tests/enforce/test_guardrail.py``.

All commands are guard inputs only: no Hermes executable is started.
"""

from __future__ import annotations

import shlex
import time
from typing import TYPE_CHECKING

import pytest

from petasos.config.sections import PetasosConfig
from petasos.guard.guard import GuardResult, ToolCallGuard
from petasos.hermes.guardrail import hermes_surface
from petasos.pipeline import Pipeline
from petasos.session.frequency import FrequencyTracker

if TYPE_CHECKING:
    from pathlib import Path

_WRITE_RULE = "petasos.selfmod.config_write"
_WRITE_COMMANDS = [
    "hermes config set command_allowlist '[ordinary]'",
    "hermes config unset command_allowlist",
    "hermes config set command_allowlist.0 replacement",
    "hermes config unset command_allowlist.0",
    "hermes config set --force command_allowlist '[]'",
    "hermes config unset --force command_allowlist.0",
    "hermes approvals suggest --apply 1,2",
    "hermes approvals suggest --apply=1",
    "hermes config edit",
    "hermes config migrate",
    "hermes setup --reset --non-interactive",
    "hermes import archive.zip",
    "hermes profile install profile.zip --force",
    "hermes profile update demo --force-config",
]


def _guard(tmp_path: Path, *, owned: bool = True) -> ToolCallGuard:
    home = tmp_path / "hermes"
    home.mkdir(exist_ok=True)
    config_path = str((home / "config.yaml").resolve())
    paths = [config_path] if owned else []
    config = PetasosConfig()
    return ToolCallGuard(
        Pipeline(config=config),
        FrequencyTracker(config),
        config,
        protected_paths=lambda: paths,
        guardrail_surface=lambda: hermes_surface(paths, roots=[str(home)]),
    )


async def _evaluate(tmp_path: Path, command: str, tool: str = "terminal") -> GuardResult:
    return await _guard(tmp_path).evaluate(tool, {"command": command}, "parity")


def _assert_write(result: GuardResult, command: str) -> None:
    assert result.selfmod_finding is not None, command
    assert result.selfmod_finding.rule_id == _WRITE_RULE, command
    assert result.selfmod_target is not None, command


def _wrap(command: str, form: str) -> str:
    if form == "absolute":
        return "/opt/tools/bin/" + command
    if form == "env":
        return "MODE=test " + command
    if form == "env-command":
        return "env MODE=test " + command
    if form == "quoted":
        return command.replace("hermes", "'/opt/tools with spaces/hermes'", 1)
    if form == "sh":
        return "sh -c " + shlex.quote(command)
    if form in {";", "&&", "|"}:
        return "printf ok " + form + " " + command + " " + form + " cat"
    if form == "newline":
        return "printf ok\n" + command
    if form == "continued":
        return command.replace("hermes ", "hermes \\\n", 1)
    return command


@pytest.mark.parametrize("command", _WRITE_COMMANDS)
@pytest.mark.parametrize(
    "form",
    [
        "bare",
        "absolute",
        "env",
        "env-command",
        "quoted",
        "sh",
        ";",
        "&&",
        "|",
        "newline",
        "continued",
    ],
)
async def test_cli_writers(tmp_path: Path, command: str, form: str) -> None:
    wrapped = _wrap(command, form)
    result = await _evaluate(tmp_path, wrapped)
    _assert_write(result, wrapped)
    assert result.selfmod_target is not None
    assert result.selfmod_target.startswith("hermes ")
    assert "ordinary" not in result.selfmod_target


@pytest.mark.parametrize("tool", ["bash", "shell", "exec", "mcp__local__terminal"])
async def test_shell_tool_names(tmp_path: Path, tool: str) -> None:
    _assert_write(await _evaluate(tmp_path, _WRITE_COMMANDS[0], tool), tool)


@pytest.mark.parametrize("verb", ["set", "unset"])
@pytest.mark.parametrize(
    "key", ["command_allowlist", "command_allowlist.0", "command_allowlist.12"]
)
@pytest.mark.parametrize(
    "value", ["'[]'", "ordinary", "'$(printf ordinary)'", "'plugin_rule:petasos.degraded'"]
)
async def test_list_keys_and_values(tmp_path: Path, verb: str, key: str, value: str) -> None:
    command = f"hermes config {verb} --force {key} {value if verb == 'set' else ''}"
    _assert_write(await _evaluate(tmp_path, command), command)


@pytest.mark.parametrize(
    ("route", "flag", "minimum"),
    [
        ("approvals suggest", "--apply", 3),
        ("setup", "--reset", 5),
        ("profile install demo", "--force", 3),
        ("profile update demo", "--force-config", 3),
    ],
)
@pytest.mark.parametrize("joined", [False, True])
async def test_flag_abbreviations(
    tmp_path: Path, route: str, flag: str, minimum: int, joined: bool
) -> None:
    for length in range(minimum, len(flag) + 1):
        command = f"hermes {route} {flag[:length]}" + ("=1" if joined else " 1")
        _assert_write(await _evaluate(tmp_path, command), command)


@pytest.mark.parametrize(
    "command",
    [
        "hermes config show",
        "hermes config get command_allowlist",
        "hermes config set other_key '[]'",
        "hermes config unset command_allowlist_extra",
        "hermes config set model.default some-model",
        "hermes config set petasos_notes hello",
        "hermes plugins disable other-plugin",
        "hermes plugins list petasos",
        "python -m hermes_cli.main config show",
        "git config set core.editor vim",
        "npm config set registry https://registry.example.test",
        "h config set model.default some-model",
        "h config get command_allowlist",
        "hermes approvals test -- echo ok",
        "hermes approvals suggest",
        "hermes approvals suggest --json --days 1",
        "hermes approvals suggest; printf -- --apply",
        "hermes approvals suggest\nprintf -- --apply",
        "hermes plugins list",
        "hermes setup model",
        "hermes profile install profile.zip",
        "hermes profile update demo",
        "hermes backup --quick",
        "other-hermes config set other_key '[]'",
    ],
)
async def test_read_only_and_unrelated_commands(tmp_path: Path, command: str) -> None:
    for wrapped in (command, "/opt/tools/bin/" + command, "sh -c " + shlex.quote(command)):
        result = await _evaluate(tmp_path, wrapped)
        assert result.selfmod_finding is None, wrapped
        assert result.selfmod_target is None, wrapped


async def test_a_profile_switch_is_a_change(tmp_path: Path) -> None:
    # Stricter than 0.5.0, which leaves this alone: running Hermes against
    # another profile's home is itself a change.
    command = "hermes -p work config set other_key 1"
    for wrapped in (command, "/opt/tools/bin/" + command, "sh -c " + shlex.quote(command)):
        _assert_write(await _evaluate(tmp_path, wrapped), wrapped)


async def test_only_the_exact_plain_enable_is_left_alone(tmp_path: Path) -> None:
    # Stricter than 0.5.0, which leaves every form alone: only the whole
    # command text, exactly, is exempt; inside ``sh -c`` it is a change.
    command = "hermes plugins enable petasos"
    for exempt in (command, "/opt/tools/bin/" + command):
        result = await _evaluate(tmp_path, exempt)
        assert result.selfmod_finding is None, exempt
    wrapped = "sh -c " + shlex.quote(command)
    _assert_write(await _evaluate(tmp_path, wrapped), wrapped)


async def test_cli_classification_needs_no_owned_paths(tmp_path: Path) -> None:
    guard = _guard(tmp_path, owned=False)
    result = await guard.evaluate("terminal", {"command": _WRITE_COMMANDS[0]}, "no-paths")
    _assert_write(result, _WRITE_COMMANDS[0])


async def test_command_text_is_conservatively_flagged(tmp_path: Path) -> None:
    command = "printf %s " + shlex.quote(_WRITE_COMMANDS[0])
    _assert_write(await _evaluate(tmp_path, command), command)


_VARIANT_COMMANDS = [
    # Hermes's global options, before the subcommand and after it.
    "hermes -p work config set command_allowlist '[]'",
    "hermes --profile work config set command_allowlist '[]'",
    "hermes --profile=work config unset command_allowlist",
    "hermes --json config set command_allowlist '[]'",
    "hermes config -p work set command_allowlist '[]'",
    "hermes config set -p work command_allowlist '[]'",
    "hermes -m some-model -p work approvals suggest --apply",
    "hermes -p work import archive.zip",
    # Other spellings of the program.
    "ai.hermes config set command_allowlist '[]'",
    "/Applications/Hermes.app/Contents/MacOS/ai.hermes config unset command_allowlist",
    "hermes.exe config set command_allowlist '[]'",
    "HERMES config set command_allowlist '[]'",
    "python -m hermes_cli.main config set command_allowlist '[]'",
    "python3.11 -m hermes_cli config unset command_allowlist",
    "python -u -m hermes_cli.main config set command_allowlist '[]'",
    "python3 -X dev -B -m hermes_cli config unset command_allowlist",
    "python -um hermes_cli.main config set command_allowlist '[]'",
    "/opt/venv/bin/python -mhermes_cli.main setup --reset",
    # Command substitution.
    "echo `hermes config set command_allowlist '[]'`",
    "echo $(hermes config set command_allowlist '[]')",
    # Petasos's own settings and whether Hermes loads it.
    "hermes config set petasos.tool_guard_enabled false",
    "hermes config unset petasos",
    "hermes config set plugins.enabled '[]'",
    "hermes config set plugins.disabled '[petasos]'",
    "hermes plugins disable petasos",
    "hermes -p work plugins uninstall petasos",
    "hermes plugins remove --yes petasos",
    # A Windows path to the program.
    "C:\\Tools\\hermes.exe config set command_allowlist x",
    # A program word that cannot be resolved still names the guarded key.
    "H=hermes; $H config set command_allowlist x",
    "alias h=hermes; h config set command_allowlist x",
    "$HERMES_BIN -p work config unset command_allowlist",
    "h config set petasos.tool_guard_enabled false",
    # Hermes's approval settings.
    "hermes config set approvals.timeout 120",
    "hermes config unset approvals",
    "$H config set approvals.mode off",
    "other-hermes config set command_allowlist '[]'",
    # Cases the 0.5.0 guard flagged and an earlier redesign build missed.
    "h -p work config unset command_allowlist",
    "$H -p work config set approvals.mode off",
    "h --profile=work config unset petasos",
    "h -c session config set command_allowlist x",
]


@pytest.mark.parametrize("command", _VARIANT_COMMANDS)
async def test_other_spellings_and_guardrail_keys(tmp_path: Path, command: str) -> None:
    """A global option, another program name or a wrapper does not hide a config writer."""
    for wrapped in (command, "cd /tmp && " + command, "sh -c " + shlex.quote(command)):
        _assert_write(await _evaluate(tmp_path, wrapped), wrapped)


_INVOCATION_FORMS = [
    "hermes.exe",
    r"C:\Tools\hermes.exe",
    "ai.hermes",
    "python -m hermes_cli.main",
    "python3.11 -m hermes_cli",
    "python -u -m hermes_cli.main",
    "python3 -X dev -B -m hermes_cli",
    "python -um hermes_cli.main",
    "/opt/venv/bin/python -mhermes_cli.main",
]


@pytest.mark.parametrize("program", _INVOCATION_FORMS)
async def test_invocation_forms_name_the_hermes_route(tmp_path: Path, program: str) -> None:
    """Each spelling is read as Hermes itself, not through the unknown-program reading."""
    result = await _evaluate(tmp_path, f"{program} config edit")
    assert result.selfmod_target == "hermes config edit"


async def test_long_commands_stay_linear(tmp_path: Path) -> None:
    """Many candidate words cost a bounded amount of work."""
    result = await _evaluate(tmp_path, "echo " + "config " * 400)
    assert result.selfmod_finding is None
    started = time.monotonic()
    result = await _evaluate(tmp_path, "echo " + "config " * 20000)
    assert time.monotonic() - started < 5.0
    _assert_write(result, "config words")
    assert result.selfmod_target == "command too long to inspect"
    started = time.monotonic()
    result = await _evaluate(tmp_path, "; ".join(["echo config"] * 100000))
    assert time.monotonic() - started < 5.0
    assert result.selfmod_finding is None


@pytest.mark.parametrize(
    "command",
    [
        "hermes config edit --help",
        "hermes plugins disable petasos -h",
        "hermes config set command_allowlist x # --help",
        "hermes config set approvals.timeout 120 # -h",
    ],
)
async def test_help_words_do_not_exempt_a_writer(tmp_path: Path, command: str) -> None:
    _assert_write(await _evaluate(tmp_path, command), command)


_WRITER = "hermes config set command_allowlist x"


@pytest.mark.parametrize(
    "command",
    [
        "true; " * 64 + _WRITER,
        "true; " * 1000 + _WRITER,
        " " * 100_001 + _WRITER,
        "echo " + "a" * 100_000 + "; " + _WRITER,
        "sh -c "
        + shlex.quote(
            "sh -c " + shlex.quote("sh -c " + shlex.quote("sh -c " + shlex.quote(_WRITER)))
        ),
    ],
    ids=["64-commands", "1000-commands", "blanks", "long-word", "nested"],
)
async def test_a_writer_past_a_bound_is_not_allowed(tmp_path: Path, command: str) -> None:
    """Text past a recognition bound is read, or reported; never allowed unread."""
    _assert_write(await _evaluate(tmp_path, command), command[-60:])
