"""A stopped enforcer refuses calls regardless of its previous failure policy."""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import Literal

import pytest

from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.enforce import Allow, Block, Enforcer, SettingsSnapshot, ToolCall


@pytest.mark.parametrize("mode", ["open", "degraded", "closed"])
@pytest.mark.parametrize("armed", [False, True])
def test_closed_enforcer_refuses_even_under_open_or_disarmed_policy(
    mode: Literal["open", "degraded", "closed"], armed: bool
) -> None:
    snapshot = SettingsSnapshot(
        armed=armed, config=replace(PetasosConfig(), fail_mode=mode), secrets=Secrets(), token=1
    )
    enforcer = Enforcer(lambda: snapshot, registry=())
    enforcer.start()
    assert enforcer.settle(10)
    enforcer.close()
    result = enforcer.tool_call(ToolCall("read_file", session="s"))
    assert isinstance(result, Block)
    assert result.message


@pytest.mark.parametrize("raised", [False, True])
def test_close_while_deciding_cannot_return_an_open_policy_allow(
    raised: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = SettingsSnapshot(
        armed=True,
        config=replace(PetasosConfig(), fail_mode="open"),
        secrets=Secrets(),
        token=1,
    )
    enforcer = Enforcer(lambda: snapshot, registry=())
    enforcer.start()
    assert enforcer.settle(10)
    entered, release = threading.Event(), threading.Event()

    def pending(core: object, call: ToolCall) -> Allow:
        entered.set()
        assert release.wait(2.0)
        if raised:
            raise RuntimeError("closed during evaluation")
        return Allow()

    monkeypatch.setattr("petasos.enforce.enforcer.decide", pending)
    results: list[object] = []
    worker = threading.Thread(
        target=lambda: results.append(enforcer.tool_call(ToolCall("read_file", session="s"))),
        daemon=True,
    )
    worker.start()
    try:
        assert entered.wait(1.0)
        enforcer.close()
        release.set()
        worker.join(timeout=1.0)
        assert not worker.is_alive()
        assert len(results) == 1
        assert isinstance(results[0], Block)
        assert results[0].message
    finally:
        release.set()
        worker.join(timeout=1.0)
        enforcer.close()
