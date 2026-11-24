"""Regression cases from the delta review of guard parity with 0.5.0.

Each case is the review's input, or the smallest equivalent of it. The
protected path is a name under a temporary directory; nothing there is
created, read or run. Every command is a guard input only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from petasos.guard import bounds, guardrail, paths
from petasos.guard.guardrail import recognize
from petasos.hermes.guardrail import hermes_surface

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from petasos.guard.surface import GuardrailHit

_TOO_DEEP = "command nested too deeply to inspect"
_TOO_LONG = "command too long to inspect"
_NAME = "pet-delta-fixture"


def _recognize(
    tmp_path: Path,
    text: str,
    tool: str = "terminal",
    *,
    environ: Mapping[str, str] | None = None,
) -> GuardrailHit | None:
    protected = str(tmp_path.resolve() / _NAME)
    key = "code" if tool == "execute_code" else "command"
    return recognize(
        tool,
        {key: text},
        protected=(protected,),
        surface=hermes_surface((protected,), roots=()),
        package=(),
        environ=environ or {},
        cwd=str(tmp_path.resolve()),
    )


def _path_budget(monkeypatch: pytest.MonkeyPatch, chars: int) -> None:
    defaults = bounds._Work.__init__.__defaults__
    assert defaults is not None
    monkeypatch.setattr(bounds._Work.__init__, "__defaults__", (defaults[0], chars, defaults[2]))


def test_a_spent_path_budget_inside_a_read_expression_is_not_an_allow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The path pieces left unread sit inside a join that is itself a read."""
    base = str(tmp_path.resolve())
    literal = f"{base}/{_NAME}"
    code = f"open('{literal}').read()\nopen(os.path.join(os.getenv('BASE'), '{_NAME}')).read()\n"
    environ = {"BASE": base}
    # With the whole budget both reads are allowed.
    assert _recognize(tmp_path, code, "execute_code", environ=environ) is None
    # The first literal and the working directory use the budget up exactly.
    _path_budget(monkeypatch, len(literal) + len(base) + 16)
    hit = _recognize(tmp_path, code, "execute_code", environ=environ)
    assert hit is not None and hit.target == _TOO_LONG


@pytest.mark.parametrize(
    ("tool", "key", "text"),
    [
        ("execute_code", "code", "print(1)"),
        ("terminal", "command", "true"),
        ("write_file", "path", "x"),
    ],
)
def test_a_spent_budget_with_no_change_found_is_too_long_for_every_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str, key: str, text: str
) -> None:
    """Whatever spent the budget and then found nothing, the answer is not an allow."""

    def spend(*args: object, **_kwargs: object) -> None:
        owned = next(arg for arg in args if isinstance(arg, paths._Owned))
        owned.work.spend_path(bounds._PATH_BUDGET + 1)

    for name in ("_judge_code", "_command_change", "_path_change"):
        monkeypatch.setattr(guardrail, name, spend)
    hit = recognize(tool, {key: text}, protected=(), package=(), environ={}, cwd=str(tmp_path))
    assert hit is not None and hit.target == _TOO_LONG
