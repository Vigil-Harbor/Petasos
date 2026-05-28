"""Tests for PET-48: CancelledError / BaseException handling in Pipeline.inspect()."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from petasos._types import (
    Direction,
    PipelineResult,
    ScanFinding,
    ScanResult,
    Severity,
)
from petasos.pipeline import Pipeline, _scan_one

# ---------------------------------------------------------------------------
# Stub scanners
# ---------------------------------------------------------------------------


class _CancellingScanner:
    """Scanner whose scan() raises CancelledError."""

    @property
    def name(self) -> str:
        return "cancelling"

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        raise asyncio.CancelledError()


class _KeyboardInterruptScanner:
    """Scanner whose scan() raises KeyboardInterrupt synchronously (before any await)."""

    @property
    def name(self) -> str:
        return "ki_scanner"

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        raise KeyboardInterrupt("simulated")


class _HealthyScanner:
    """Scanner that returns a normal finding."""

    @property
    def name(self) -> str:
        return "healthy"

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        return ScanResult(
            scanner_name="healthy",
            findings=(
                ScanFinding(
                    rule_id="healthy.rule",
                    finding_type="test",
                    severity=Severity.MEDIUM,
                    confidence=0.9,
                    message="test finding",
                    scanner_name="healthy",
                ),
            ),
            duration_ms=1.0,
        )


class _BlockingScanner:
    """Scanner that blocks on an event — for deterministic cancellation tests."""

    def __init__(self, started: asyncio.Event, proceed: asyncio.Event) -> None:
        self._started = started
        self._proceed = proceed

    @property
    def name(self) -> str:
        return "blocking"

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        self._started.set()
        await self._proceed.wait()
        return ScanResult(
            scanner_name="blocking",
            findings=(),
            duration_ms=0.0,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inspect_catches_cancelled_error() -> None:
    # Regression for PET-48: CancelledError must not escape inspect()
    pipe = Pipeline(scanners=[_CancellingScanner()])
    result = await pipe.inspect("test input")
    assert isinstance(result, PipelineResult)
    assert result.safe is False
    errors_joined = " ".join(result.errors)
    assert "CancelledError" in errors_joined or any(
        sr.error is not None and "CancelledError" in sr.error
        for sr in result.scanner_results
    )


@pytest.mark.asyncio
async def test_scan_one_isolates_cancelled_scanner() -> None:
    # Regression for PET-48: _scan_one must catch BaseException
    scanner = _CancellingScanner()
    result = await _scan_one(
        scanner, "test", direction="inbound", session_id=None
    )
    assert isinstance(result, ScanResult)
    assert result.error is not None
    assert "CancelledError" in result.error


@pytest.mark.asyncio
async def test_gather_return_exceptions_isolates_failure() -> None:
    # Regression for PET-48: one cancelled scanner must not abort others
    pipe = Pipeline(scanners=[_CancellingScanner(), _HealthyScanner()])
    result = await pipe.inspect("test input")
    assert isinstance(result, PipelineResult)
    # Healthy scanner's findings should be in the merged output
    assert any(f.rule_id == "healthy.rule" for f in result.findings)
    # Cancelled scanner's error should be recorded in scanner_results
    cancelled_results = [
        sr for sr in result.scanner_results
        if sr.error is not None and "CancelledError" in sr.error
    ]
    assert len(cancelled_results) >= 1


@pytest.mark.asyncio
async def test_keyboard_interrupt_caught_at_boundary() -> None:
    # Regression for PET-48: KeyboardInterrupt must not escape inspect()
    # KI is tested at the inspect() boundary (not through a scanner inside
    # asyncio.wait_for, because the event loop propagates KI from tasks
    # before _scan_one's handler can catch it).
    pipe = Pipeline()
    with patch.object(pipe, "_inspect_inner", side_effect=KeyboardInterrupt("simulated")):
        result = await pipe.inspect("test input")
    assert isinstance(result, PipelineResult)
    assert result.safe is False


@pytest.mark.asyncio
async def test_cancelled_error_logged() -> None:
    # Regression for PET-48: non-Exception BaseExceptions are logged at inspect() boundary
    pipe = Pipeline()
    with (
        patch.object(pipe, "_inspect_inner", side_effect=asyncio.CancelledError()),
        patch("petasos.pipeline._logger") as mock_logger,
    ):
        result = await pipe.inspect("test input")
    assert isinstance(result, PipelineResult)
    assert result.safe is False
    mock_logger.warning.assert_called_once()
    args = mock_logger.warning.call_args
    assert "CancelledError" in str(args)


@pytest.mark.asyncio
async def test_mid_gather_cancel_full_pipeline() -> None:
    # Regression for PET-48: external task cancellation returns PipelineResult
    started = asyncio.Event()
    proceed = asyncio.Event()
    pipe = Pipeline(scanners=[_BlockingScanner(started, proceed)])

    async def run_and_cancel() -> PipelineResult:
        task = asyncio.create_task(pipe.inspect("test input"))
        await asyncio.wait_for(started.wait(), timeout=5.0)
        task.cancel()
        proceed.set()
        try:
            return await task
        except asyncio.CancelledError:
            pytest.fail("inspect() raised CancelledError instead of returning PipelineResult")

    result = await run_and_cancel()
    assert isinstance(result, PipelineResult)
    assert result.safe is False
