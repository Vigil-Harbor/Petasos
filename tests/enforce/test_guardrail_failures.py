"""Recognition failures retain fail-mode policy across ready and fallback paths."""

from __future__ import annotations

from typing import Any

import pytest

from petasos.config.schema import from_mapping
from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.enforce import (
    Allow,
    Block,
    Enforcer,
    EvaluationFault,
    HostInfo,
    InitGate,
    SettingsSnapshot,
    ToolCall,
)
from petasos.guard.surface import GuardrailSurface


def _raise(*args: object, **kwargs: object) -> Any:
    raise RuntimeError("recognition fixture failed")


@pytest.mark.parametrize("failure", ["surface", "paths", "recognition"])
@pytest.mark.parametrize("phase", ["ready", "cold", "failed", "evaluation_failed"])
@pytest.mark.parametrize("mode", ["closed", "degraded", "open"])
@pytest.mark.parametrize("tool", ["terminal", "write_file", "read_file"])
def test_recognition_failure_follows_fail_mode_and_logs_once(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: str,
    phase: str,
    mode: str,
    tool: str,
) -> None:
    config = from_mapping(
        PetasosConfig,
        {"fail_mode": mode, "scanners": {"prompt_guard": {"enabled": "off"}}},
    )

    def surface() -> GuardrailSurface:
        return GuardrailSurface()

    def paths() -> frozenset[str]:
        return frozenset({"/owned/config.yaml"})

    if failure == "surface":
        surface = _raise
    elif failure == "paths":
        paths = _raise
    else:
        monkeypatch.setattr("petasos.guard.selfmod.recognize", _raise)
        monkeypatch.setattr("petasos.enforce.guardrail.recognize", _raise)
    gate = InitGate.held(skip_wait=True) if phase == "cold" else None
    if phase == "failed":
        gate = InitGate.failed("init fixture failed")
    fault = EvaluationFault()
    enforcer = Enforcer(
        lambda: SettingsSnapshot(armed=True, config=config, secrets=Secrets(), token=1),
        host=HostInfo(protected_paths=paths, guardrail_surface=surface, approve_directive=True),
        init=gate,
        evaluation=fault,
    )
    enforcer.start()
    if phase != "cold":
        enforcer.settle(10)
    if phase == "evaluation_failed":
        fault.arm("error")
    try:
        for _ in range(2):
            decision = enforcer.tool_call(
                ToolCall(tool=tool, args={"command": "echo ok"}, session="s")
            )
            if tool == "read_file" or (mode == "open" and phase != "evaluation_failed"):
                assert isinstance(decision, Allow)
            elif mode == "open":
                # An independent guard-evaluation failure retains its own block.
                assert isinstance(decision, Block)
                assert "Parameter scan unavailable" in decision.message
            else:
                assert isinstance(decision, Block)
                assert "guardrail check could not run" in decision.message
                assert "operator" in decision.message
        logs = [record for record in caplog.records if "GUARDRAIL_CHECK_FAILED" in record.message]
        assert len(logs) == (0 if tool == "read_file" else 1)
        if logs:
            assert "recognition fixture failed" in logs[0].message
    finally:
        if gate is not None:
            gate.release()
        enforcer.close()


def test_recognition_cause_is_logged_once_across_startup_and_ready(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gate = InitGate.held(skip_wait=True)
    config = from_mapping(PetasosConfig, {"fail_mode": "open"})
    enforcer = Enforcer(
        lambda: SettingsSnapshot(armed=True, config=config, secrets=Secrets(), token=1),
        host=HostInfo(guardrail_surface=_raise),
        init=gate,
    )
    call = ToolCall(tool="terminal", args={"command": "echo ok"}, session="same-session")
    enforcer.start()
    try:
        assert isinstance(enforcer.tool_call(call), Allow)
        gate.release()
        assert enforcer.settle(10)
        assert isinstance(enforcer.tool_call(call), Allow)
        logs = [record for record in caplog.records if "GUARDRAIL_CHECK_FAILED" in record.message]
        assert len(logs) == 1
    finally:
        gate.release()
        enforcer.close()
