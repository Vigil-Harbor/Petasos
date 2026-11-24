"""Regression cases from the review of guard parity with 0.5.0.

Each case is the review's input, or the smallest equivalent of it. Every
command is a guard input only: nothing is run.
"""

from __future__ import annotations

import json
import shlex
from typing import TYPE_CHECKING

import pytest

from petasos.guard.guardrail import recognize
from petasos.hermes.guardrail import hermes_surface

if TYPE_CHECKING:
    from pathlib import Path

    from petasos.guard.surface import GuardrailHit


def _hit(tmp_path: Path, command: str, tool: str = "terminal") -> GuardrailHit | None:
    home = tmp_path / "hermes"
    (home / "plugins" / "petasos").mkdir(parents=True, exist_ok=True)
    config = home / "config.yaml"
    config.write_text("plugins: {}\n", encoding="utf-8")
    paths = (str(config), str(home / "plugins" / "petasos"))
    key = "code" if tool == "execute_code" else "command"
    return recognize(
        tool,
        {key: command},
        protected=paths,
        surface=hermes_surface(paths, roots=(str(home),)),
        package=(),
        environ={"HERMES_HOME": str(home), "HOME": str(tmp_path)},
        cwd=str(tmp_path),
    )


def _config(tmp_path: Path) -> str:
    return str((tmp_path / "hermes" / "config.yaml").resolve())


def test_python_on_the_opening_line_keeps_the_other_interpreter_check(tmp_path: Path) -> None:
    """The Python check removes comments; Ruby's check still reads the body."""
    body = "#" + str(tmp_path / "hermes" / "config.yaml")
    command = "true; " * 63 + "python --version; ruby <<'EOF'\n" + body + "\nEOF"
    hit = _hit(tmp_path, command)
    assert hit is not None and hit.target == _config(tmp_path)


def test_any_key_in_the_plugins_mapping_is_a_change(tmp_path: Path) -> None:
    """0.5.0 guards the whole ``plugins`` mapping, in the command and in quoted text."""
    for command in (
        "hermes config set plugins.review_note demo",
        "echo 'hermes config set plugins.review_note demo'",
    ):
        hit = _hit(tmp_path, command)
        assert hit is not None and hit.target == "hermes config set plugins", command


def test_ai_hermes_exe_is_hermes(tmp_path: Path) -> None:
    hit = _hit(tmp_path, "ai.hermes.exe config edit")
    assert hit is not None and hit.target == "hermes config edit"


_TOO_DEEP = "command nested too deeply to inspect"
_TOO_LONG = "command too long to inspect"


def _sh(script: str) -> str:
    return "sh -c " + shlex.quote(script)


def test_invoke_expression_entered_at_depth_two_is_not_left_unread(tmp_path: Path) -> None:
    """The text ``iex`` runs is one level deeper; past the limit it is reported."""
    config = str(tmp_path / "hermes" / "config.yaml")
    native = "powershell -Command \"iex 'Remove-Item " + config + "'\""
    hit = _hit(tmp_path, _sh(_sh(native)))
    assert hit is not None and hit.target == _TOO_DEEP


def test_a_script_started_past_the_limit_is_reported(tmp_path: Path) -> None:
    config = str(tmp_path / "hermes" / "config.yaml")
    command = _sh(_sh(_sh("foo sh -c " + shlex.quote("rm " + config))))
    hit = _hit(tmp_path, command)
    assert hit is not None and hit.target == _TOO_DEEP


def test_python_and_its_embedded_commands_share_the_depth_count(tmp_path: Path) -> None:
    """Shell, then Python, then a command string, then a shell: four levels."""
    config = str(tmp_path / "hermes" / "config.yaml")
    code = "import os; os.system(" + json.dumps(_sh("rm " + config)) + ")"
    hit = _hit(tmp_path, _sh("python -c " + shlex.quote(code)))
    assert hit is not None and hit.target == _TOO_DEEP
    # One level less is read in full.
    hit = _hit(tmp_path, "python -c " + shlex.quote(code))
    assert hit is not None and hit.target == _config(tmp_path)


def test_embedded_commands_spend_one_word_budget(tmp_path: Path) -> None:
    """Each string alone fits the budget; together they do not."""
    piece = json.dumps("echo " + "config " * 400)
    code = f"import os\nos.system({piece})\nos.system({piece})\n"
    hit = _hit(tmp_path, code, tool="execute_code")
    assert hit is not None and hit.target == _TOO_LONG
    assert _hit(tmp_path, f"import os\nos.system({piece})\n", tool="execute_code") is None


@pytest.mark.parametrize(
    ("command", "target"),
    [
        ("printf %s hermes config edit", "hermes config edit"),
        ("echo hermes plugins disable petasos", "hermes plugins disable"),
    ],
)
def test_writer_words_in_the_command_text_are_a_change(
    tmp_path: Path, command: str, target: str
) -> None:
    hit = _hit(tmp_path, command)
    assert hit is not None and hit.target == target


def test_the_exact_plain_enable_stays_exempt(tmp_path: Path) -> None:
    assert _hit(tmp_path, "hermes plugins enable petasos") is None
    assert _hit(tmp_path, "echo hermes plugins enable petasos") is not None
