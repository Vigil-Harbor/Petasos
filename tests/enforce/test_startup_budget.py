"""The cold-start deadline follows settings unless the caller supplies limits."""

from __future__ import annotations

from dataclasses import replace

import pytest

from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.enforce import Enforcer, InitGate, Limits, ManualClock, SettingsSnapshot


@pytest.mark.parametrize("configured,expected", [(9.0, 9.0), (0.01, 0.05), (60.0, 60.0)])
def test_configured_startup_wait_sets_the_cold_deadline(
    configured: float, expected: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = PetasosConfig()
    config = replace(base, startup=replace(base.startup, wait_seconds=configured))
    snapshot = SettingsSnapshot(armed=True, config=config, secrets=Secrets(), token=1)
    clock = ManualClock(monotonic=1000.0)
    enforcer = Enforcer(lambda: snapshot, init=InitGate.held(), clock=clock, registry=())
    enforcer.start()
    waits: list[float | None] = []

    def wait(timeout: float | None = None) -> bool:
        waits.append(timeout)
        return False

    monkeypatch.setattr(enforcer._core._init_done, "wait", wait)
    try:
        assert not enforcer._core.ensure()
        assert waits == [pytest.approx(expected)]
        assert enforcer._core._deadline == pytest.approx(1000.0 + expected)
        assert not enforcer._core.ensure()
        assert len(waits) == 1
    finally:
        enforcer.close()


@pytest.mark.parametrize("override,expected", [(0.0, 2.0), (0.01, 0.05), (70.0, 60.0)])
def test_explicit_limits_keep_their_existing_bounds(override: float, expected: float) -> None:
    snapshot = SettingsSnapshot(armed=True, config=PetasosConfig(), secrets=Secrets(), token=1)
    enforcer = Enforcer(lambda: snapshot, limits=Limits(init_wait_s=override), registry=())
    try:
        assert enforcer._core._budget() == expected
    finally:
        enforcer.close()
