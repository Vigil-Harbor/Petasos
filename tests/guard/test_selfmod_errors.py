"""Pin library health, reconfiguration and self-change error handling."""

from __future__ import annotations

from typing import Any, cast

import pytest

from petasos.config.schema import from_mapping
from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.guard.guard import ToolCallGuard
from petasos.guard.guardrail import CheckFailure
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner


class _BoomParams:
    def values(self) -> Any:
        raise RuntimeError("classifier broke")


def test_a_classifier_error_does_not_raise() -> None:
    config = PetasosConfig()
    pipe = Pipeline(scanners=[MinimalScanner()], config=config)
    guard = ToolCallGuard(
        pipe,
        pipe._frequency_tracker,
        config,
        secrets=Secrets(session_secret=b"a" * 32),
        protected_paths=lambda: ["/owned/config.yaml"],
    )
    match = guard._classify_selfmod("terminal", cast("dict[str, Any]", _BoomParams()))
    assert isinstance(match, CheckFailure)


@pytest.mark.parametrize("mode", ["closed", "degraded", "open"])
async def test_a_failing_classifier_refuses_writes_and_logs_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, mode: str
) -> None:
    config = from_mapping(PetasosConfig, {"fail_mode": mode})
    pipe = Pipeline(scanners=[MinimalScanner()], config=config)
    guard = ToolCallGuard(
        pipe,
        pipe._frequency_tracker,
        config,
        protected_paths=lambda: ["/owned/config.yaml"],
    )

    def fail(value: object, depth: int = 0) -> list[str]:
        raise RuntimeError("argument recognition failed")

    monkeypatch.setattr(guard, "_extract_leaf_strings", fail)
    for _ in range(2):
        result = await guard.evaluate("terminal", {"nested": ["hi"]}, "s")
        assert result.allowed is (mode == "open")
        assert result.guardrail_check_failed
        if mode != "open":
            assert "guardrail check could not run" in result.reason
        assert result.selfmod_target is None
    logs = [record for record in caplog.records if "GUARDRAIL_CHECK_FAILED" in record.message]
    assert len(logs) == 1
    assert "argument recognition failed" in logs[0].message
    read = await guard.evaluate("read_file", {"nested": ["hi"]}, "s")
    assert read.allowed
    assert not read.guardrail_check_failed
