"""Recognition cost grows linearly with the length of the text.

Each family of inputs is grown four and sixteen times. Its time may grow by
up to three times the growth of the input, plus a small fixed allowance for
timer noise. A quadratic path grows sixteen and 256 times. The bounds are
generous on purpose: they catch a quadratic path, not a slow machine.
Every command is a guard input only: nothing is run.
"""

from __future__ import annotations

import functools
import time
from typing import TYPE_CHECKING

import pytest

from petasos.guard import paths
from petasos.guard.bounds import _SEEN_LIMIT
from petasos.guard.guardrail import recognize
from petasos.hermes.guardrail import hermes_surface

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from petasos.guard.surface import GuardrailHit

_SLACK = 3
_NOISE = 0.05


def _recognizer(tmp_path: Path) -> Callable[[str, str], GuardrailHit | None]:
    home = tmp_path / "hermes"
    (home / "plugins" / "petasos").mkdir(parents=True, exist_ok=True)
    config = home / "config.yaml"
    config.write_text("plugins: {}\n", encoding="utf-8")
    protected = (str(config), str(home / "plugins" / "petasos"))
    surface = hermes_surface(protected, roots=(str(home),))
    env = {"HERMES_HOME": str(home), "HOME": str(tmp_path)}

    def run(text: str, tool: str) -> GuardrailHit | None:
        key = "code" if tool == "execute_code" else "command"
        return recognize(
            tool,
            {key: text},
            protected=protected,
            surface=surface,
            package=(),
            environ=env,
            cwd=str(tmp_path),
        )

    return run


def _timed(run: Callable[[], GuardrailHit | None]) -> tuple[float, GuardrailHit | None]:
    best = float("inf")
    hit = None
    for _ in range(3):
        started = time.perf_counter()
        hit = run()
        best = min(best, time.perf_counter() - started)
    return best, hit


def _assert_linear(
    tmp_path: Path, make: Callable[[int], str], base: int, tool: str = "terminal"
) -> list[GuardrailHit | None]:
    recognise = _recognizer(tmp_path)
    times: list[float] = []
    hits: list[GuardrailHit | None] = []
    for growth in (1, 4, 16):
        elapsed, hit = _timed(functools.partial(recognise, make(base * growth), tool))
        times.append(elapsed)
        hits.append(hit)
    for growth, elapsed in zip((4, 16), times[1:], strict=True):
        assert elapsed <= _SLACK * growth * times[0] + _NOISE, (growth, times)
    return hits


def test_a_long_powershell_pipeline_costs_linear_time(tmp_path: Path) -> None:
    def make(count: int) -> str:
        return 'powershell -Command "' + " | ".join(["Get-Item a"] * count) + '"'

    assert _assert_linear(tmp_path, make, 500) == [None, None, None]


def test_a_growing_working_directory_costs_linear_time(tmp_path: Path) -> None:
    """Each ``cd`` lengthens the directory; the path budget ends the growth."""

    def make(count: int) -> str:
        return "cd aa; " * count + "rm x"

    hits = _assert_linear(tmp_path, make, 400)
    last = hits[-1]
    assert last is not None and last.target == "command too long to inspect"


def test_many_protected_path_uses_in_program_text_cost_linear_time(tmp_path: Path) -> None:
    config = str(tmp_path / "hermes" / "config.yaml")

    def make(count: int) -> str:
        line = f"print(open('{config}').read(), Path('{config}').exists())"
        return "\n".join([line] * count)

    assert _assert_linear(tmp_path, make, 300, tool="execute_code") == [None, None, None]


@pytest.mark.parametrize(
    "make",
    [
        lambda count: " ".join(["echo 'x hermes config get a';"] * count),
        lambda count: "echo " + " ".join(["'say \"hermes config get a\" now'"] * count),
    ],
    ids=["many-quoted-words", "quoted-in-quoted"],
)
def test_reading_quoted_text_costs_linear_time(tmp_path: Path, make: Callable[[int], str]) -> None:
    assert _assert_linear(tmp_path, make, 300) == [None, None, None]


def test_the_path_cache_keeps_a_bounded_size(tmp_path: Path) -> None:
    owned = paths._Owned({}, ())
    cwd = str(tmp_path)
    for _ in range(2000):
        cwd += "/aa"
        paths._match_path("x", owned, {}, cwd)
    kept = sum(len(key[0]) + len(key[2]) for key in owned.seen)
    assert kept <= _SEEN_LIMIT
    assert owned.work.retained <= _SEEN_LIMIT
