"""Keep the recorded verdicts independent of the shell and the machine's clock."""

from __future__ import annotations

import itertools
import time
from types import SimpleNamespace

import pytest

from petasos.session import frequency


@pytest.fixture(autouse=True)
def _no_exported_hermes_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replay without ``HERMES_HOME``.

    A relative name such as ``config.yaml`` is tried against the Hermes home
    when one is exported, so two corpus cases gain a self-change finding that
    the record, made without it, does not have.
    """
    monkeypatch.delenv("HERMES_HOME", raising=False)


@pytest.fixture(autouse=True)
def _risk_score_clock_always_moves(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the tracker a clock that moves a microsecond on every reading.

    Several session cases put a score exactly on a tier threshold. The record
    was made where some time always passes between two steps, so the score
    had decayed just below it. Where the system clock moves in steps of
    15 ms, as on Windows, no time passes and the tier is reached one step
    early.
    """
    start = time.monotonic()
    ticks = itertools.count(1)
    moving = SimpleNamespace(monotonic=lambda: start + next(ticks) * 1e-6)
    monkeypatch.setattr(frequency, "time", moving)
