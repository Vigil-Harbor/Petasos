"""SCAN-03 (PET-61): cancellation frees the event loop; worker-thread residual.

Distinct from PET-48 (test_cancel_mid_gather): this pins the *observable
contract* — cancelling an in-flight inspect() resolves promptly (well before the
worker thread would finish) and the pipeline stays usable — and documents that
the to_thread worker keeps running after cancellation.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from petasos._types import Direction, PipelineResult, ScanResult
from petasos.config import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner

_WORKER_SLEEP = 1.0


class _ToThreadScanner:
    """Mirrors the ML wrappers: blocking work dispatched via asyncio.to_thread."""

    def __init__(self, started: asyncio.Event) -> None:
        self._started = started
        self.thread_finished = False

    @property
    def name(self) -> str:
        return "to_thread"

    def _blocking(self) -> None:
        time.sleep(_WORKER_SLEEP)
        self.thread_finished = True

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        self._started.set()
        await asyncio.to_thread(self._blocking)
        return ScanResult(scanner_name="to_thread", findings=())


@pytest.mark.asyncio
async def test_cancel_frees_loop_and_pipeline_reusable() -> None:
    started = asyncio.Event()
    scanner = _ToThreadScanner(started)
    # generous timeout so the PIPE-03 timeout path doesn't fire — testing cancel
    pipe = Pipeline(
        [MinimalScanner(), scanner],
        config=PetasosConfig(scanner_timeout_seconds=30.0),
    )

    task = asyncio.create_task(pipe.inspect("text"))
    await asyncio.wait_for(started.wait(), timeout=5.0)

    t0 = time.perf_counter()
    task.cancel()
    # inspect() catches BaseException (PET-48) and must return a PipelineResult,
    # not propagate CancelledError.
    first = await task
    assert isinstance(first, PipelineResult)
    elapsed = time.perf_counter() - t0

    # The event loop was freed without waiting the full worker sleep.
    assert elapsed < 0.5
    # Residual: the worker thread is still running (frees loop, not the thread).
    assert scanner.thread_finished is False

    # The pipeline remains usable for a subsequent inspect().
    started.clear()
    second = await pipe.inspect("hello world")
    assert isinstance(second, PipelineResult)
