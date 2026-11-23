"""Keep the recorded risk scores independent of the machine's clock."""

from __future__ import annotations

import itertools
import time
from types import SimpleNamespace

import pytest

from petasos.session import frequency


@pytest.fixture(autouse=True)
def _risk_score_clock_always_moves(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the tracker a clock that moves a microsecond on every reading.

    The tracker reads the system clock, not the clock the adapters hand the
    enforcer. One recorded score sits on a rounding boundary: 3.75 is shown
    as 3.8, and as 3.7 once any time at all has passed. Where the system
    clock moves in steps of 15 ms, as on Windows, two events can fall in the
    same step, no time passes, and the record does not match.
    """
    start = time.monotonic()
    ticks = itertools.count(1)
    moving = SimpleNamespace(monotonic=lambda: start + next(ticks) * 1e-6)
    monkeypatch.setattr(frequency, "time", moving)
