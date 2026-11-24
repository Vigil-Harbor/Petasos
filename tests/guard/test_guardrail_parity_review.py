"""Regression cases from the review of guard parity with 0.5.0.

Each case is the review's input, or the smallest equivalent of it. Every
command is a guard input only: nothing is run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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
