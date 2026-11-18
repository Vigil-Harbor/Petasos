"""Rejected reloads preserve the whole running enforcement tree."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.enforce import Enforcer, HostInfo, SettingsSnapshot, ToolCall

if TYPE_CHECKING:
    from petasos.enforce.engine import Engine


def _state(enforcer: Enforcer, engine: Engine) -> tuple[object, ...]:
    assert engine.lineage is not None
    return (
        engine.config,
        engine.pipeline.config,
        engine.guard._config,
        engine.guard._origin.copy(),
        engine.guard._spawn_budget._window,
        engine.tracker.config,
        engine.tracker._terminated_ids.copy(),
        engine.lineage.config,
        engine.lineage.ancestors("child"),
        engine.taint._config,
        engine.taint.tainted_source("parent", {"text": "a confidential source document"}),
        engine.egress,
        engine.namespaces,
        enforcer._core.armed,
        enforcer._core.fail_mode,
        enforcer._core._token,
    )


@pytest.mark.parametrize("failure", ["delegate", "weights", "late"])
def test_rejected_reload_preserves_all_state_and_can_recover(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = PetasosConfig()
    snapshot = SettingsSnapshot(armed=True, config=config, secrets=Secrets(), token=1)
    enforcer = Enforcer(lambda: snapshot, host=HostInfo(subagent_hooks=True), registry=())
    enforcer.start()
    assert enforcer.settle(10)
    engine = enforcer._core.engine
    assert engine is not None and engine.lineage is not None
    engine.lineage.register("child", "parent")
    engine.taint.capture("parent", "a confidential source document", "source")
    engine.tracker._terminated_ids.update({"old-one": None, "old-two": None})
    before = _state(enforcer, engine)
    proposed = replace(
        config,
        fail_mode="open",
        normalization=replace(config.normalization, nfkc=not config.normalization.nfkc),
        sessions=replace(config.sessions, max_tombstones=1),
        egress=replace(config.egress, sink_tools=("new_sink",), taint_namespaces=("new_source",)),
    )
    if failure == "delegate":
        proposed = replace(
            proposed, tools=replace(config.tools, exempt=(config.tools.delegate_names[0],))
        )
    elif failure == "weights":
        original_parse = engine.tracker.__class__.apply_config

        def bad_weights(tracker: object, new: PetasosConfig) -> None:
            if new.normalization != config.normalization:
                raise ValueError("weight parse refused")
            original_parse(tracker, new)  # type: ignore[arg-type]

        monkeypatch.setattr(engine.tracker.__class__, "apply_config", bad_weights)
    else:
        original = engine.taint.apply_config

        def refuse(new: PetasosConfig) -> None:
            original(new)
            raise RuntimeError("late reload failure")

        monkeypatch.setattr(engine.taint, "apply_config", refuse)
    snapshot = SettingsSnapshot(armed=False, config=proposed, secrets=Secrets(), token=2)
    try:
        enforcer.refresh()
        assert _state(enforcer, engine) == before
        # Observation without refresh must not install rejected switches either.
        enforcer.status()
        assert _state(enforcer, engine) == before
        monkeypatch.undo()
        snapshot = SettingsSnapshot(
            armed=True,
            config=replace(config, normalization=proposed.normalization),
            secrets=Secrets(),
            token=3,
        )
        enforcer.refresh()
        assert engine.pipeline.config.normalization == proposed.normalization
        assert engine.config == engine.pipeline.config
        assert enforcer._core._token == 3
        assert enforcer.tool_call(ToolCall("read_file", session="child")) is not None
    finally:
        enforcer.close()
