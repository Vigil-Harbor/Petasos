"""Pin library health, reconfiguration and self-change error handling."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from petasos.config.schema import from_mapping
from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.guard.guard import ToolCallGuard
from petasos.guard.guardrail import CheckFailure
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner

if TYPE_CHECKING:
    from pathlib import Path


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
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
    mode: str,
) -> None:
    config = from_mapping(PetasosConfig, {"fail_mode": mode})
    pipe = Pipeline(scanners=[MinimalScanner()], config=config)
    # An absolute path on every system: "/owned/config.yaml" has no drive on Windows.
    owned = str(tmp_path / "owned" / "config.yaml")
    guard = ToolCallGuard(
        pipe,
        pipe._frequency_tracker,
        config,
        protected_paths=lambda: [owned],
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


async def test_a_failed_read_of_the_protected_paths_keeps_the_last_set(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read that fails after a good one still protects the same file."""
    owned = tmp_path / "config.yaml"
    owned.write_text("enabled: true\n")
    config = PetasosConfig()
    pipe = Pipeline(scanners=[MinimalScanner()], config=config)
    state = {"fail": False}

    def paths() -> list[str]:
        if state["fail"]:
            raise OSError("the profile could not be read")
        return [str(owned)]

    guard = ToolCallGuard(pipe, pipe._frequency_tracker, config, protected_paths=paths)
    first = await guard.evaluate("write_file", {"path": str(owned), "content": "x"}, "s1")
    assert first.selfmod_target is not None
    state["fail"] = True
    guard._selfmod_owned_cache = (0.0, guard._selfmod_owned_cache[1])
    again = await guard.evaluate("write_file", {"path": str(owned), "content": "x"}, "s1")
    assert again.selfmod_target is not None
    assert again.guardrail_check_failed is False
    other = await guard.evaluate(
        "write_file", {"path": str(tmp_path / "notes.md"), "content": "x"}, "s2"
    )
    assert other.allowed and other.guardrail_check_failed is False


async def test_a_failed_first_read_of_the_protected_paths_is_a_failed_check() -> None:
    config = PetasosConfig()
    pipe = Pipeline(scanners=[MinimalScanner()], config=config)

    def paths() -> list[str]:
        raise OSError("the profile could not be read")

    guard = ToolCallGuard(pipe, pipe._frequency_tracker, config, protected_paths=paths)
    result = await guard.evaluate("write_file", {"path": "/tmp/notes.md", "content": "x"}, "s1")
    assert result.guardrail_check_failed is True
    assert result.allowed is False
