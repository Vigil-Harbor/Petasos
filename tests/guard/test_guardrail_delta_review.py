"""Regression cases from the delta review of guard parity with 0.5.0.

Each case is the review's input, or the smallest equivalent of it. The
protected path is a name under a temporary directory; nothing there is
created, read or run. Every command is a guard input only.
"""

from __future__ import annotations

import shlex
import time
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


def test_a_long_environment_join_costs_linear_time(tmp_path: Path) -> None:
    """Each piece lengthens the path; the budget ends the chain at its first exhaustion."""

    def make(count: int) -> str:
        return "p = os.getenv('BASE')" + " + 'a'" * count + "\n"

    environ = {"BASE": str(tmp_path.resolve())}
    times: list[float] = []
    hits: list[GuardrailHit | None] = []
    for growth in (1, 4, 16):
        code = make(8000 * growth)
        best = float("inf")
        for _ in range(3):
            started = time.perf_counter()
            hit = _recognize(tmp_path, code, "execute_code", environ=environ)
            best = min(best, time.perf_counter() - started)
        times.append(best)
        hits.append(hit)
    for growth, elapsed in zip((4, 16), times[1:], strict=True):
        assert elapsed <= 3 * growth * times[0] + 0.05, (growth, times)
    assert all(hit is not None and hit.target == _TOO_LONG for hit in hits)


def test_one_path_larger_than_the_cache_is_not_kept(tmp_path: Path) -> None:
    """The working directory fits the path budget; with ``HOME`` the entry does not fit."""
    owned = paths._Owned({}, ())
    cwd = str(tmp_path) + "/" + "a" * (bounds._SEEN_LIMIT // 2)
    home = str(tmp_path) + "/" + "h" * (bounds._SEEN_LIMIT // 2)
    paths._match_path("x", owned, {"HOME": home}, cwd)
    assert owned.work.path_chars >= 0
    assert owned.work.retained <= bounds._SEEN_LIMIT
    assert sum(len(key[0]) + len(key[2]) for key in owned.seen) <= bounds._SEEN_LIMIT


def _sh(script: str) -> str:
    return "sh -c " + shlex.quote(script)


@pytest.mark.parametrize(
    "body",
    ["print('{path}')", "open('{path}', 'w').write('x')"],
    ids=["names", "writes"],
)
@pytest.mark.parametrize("interpreter", ["python", "ruby"])
def test_a_here_document_in_a_shell_script_is_read_as_its_program(
    tmp_path: Path, body: str, interpreter: str
) -> None:
    """The same text passed directly and as the sole script of ``sh -c`` or ``eval``."""
    path = str(tmp_path.resolve() / _NAME)
    text = f"{interpreter} <<END\n{body.format(path=path)}\nEND"
    for command in (text, _sh(text), "eval " + shlex.quote(text)):
        hit = _recognize(tmp_path, command)
        assert hit is not None and hit.target == path, command


def test_a_here_document_past_the_depth_limit_is_not_read(tmp_path: Path) -> None:
    """Shell, Python, then a command string whose here-document would be a fourth level."""
    code = 'import os; os.system("python <<END\nprint(1)\nEND")'
    hit = _recognize(tmp_path, _sh("python -c " + shlex.quote(code)))
    assert hit is not None and hit.target == _TOO_DEEP
    # One level less is read, and the body changes nothing.
    assert _recognize(tmp_path, "python -c " + shlex.quote(code)) is None


@pytest.mark.parametrize(
    "program",
    [
        "ai.hermes.exe",
        "hermes.exe",
        "ai.hermes",
        "/opt/tools/bin/ai.hermes.exe",
        "timeout 5 ai.hermes.exe",
        "python -m hermes_cli",
    ],
)
@pytest.mark.parametrize("option", ["--version", "--help"])
def test_a_hermes_alias_keeps_the_operand_check_of_the_word_as_written(
    tmp_path: Path, program: str, option: str
) -> None:
    """Reading the alias as ``hermes`` only adds a reading; ``name`` is still a file."""
    hit = _recognize(tmp_path, f"{program} {option} {_NAME}")
    assert hit is not None and hit.target == str(tmp_path.resolve() / _NAME)
    # Hermes's own verbs stay verbs.
    assert _recognize(tmp_path, f"{program} plugins list") is None
