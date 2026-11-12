"""Pin prompt cancellation while acknowledging residual worker-thread execution.

See docs/architecture/rationale.md, "Test timing and backend qualification"."""

from __future__ import annotations

import asyncio
import time

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
from petasos.model import Direction, PipelineResult, ScanResult
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
        """Return the fixture scanner name."""
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
        """Supply the configured scanner response for this fixture."""
        self._started.set()
        await asyncio.to_thread(self._blocking)
        return ScanResult(scanner_name="to_thread", findings=())


async def test_cancel_frees_loop_and_pipeline_reusable() -> None:
    """Pin cancel frees loop and pipeline reusable."""
    started = asyncio.Event()
    scanner = _ToThreadScanner(started)
    # The generous timeout isolates cancellation from deadline expiry.
    pipe = Pipeline(
        [MinimalScanner(), scanner],
        config=from_mapping(PetasosConfig, {"scanners": {"timeout_seconds": 30.0}}),
    )

    task = asyncio.create_task(pipe.inspect("text"))
    await asyncio.wait_for(started.wait(), timeout=5.0)

    t0 = time.perf_counter()
    task.cancel()
    first = await task
    assert isinstance(first, PipelineResult)
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.5
    assert scanner.thread_finished is False

    started.clear()
    second = await pipe.inspect("hello world")
    assert isinstance(second, PipelineResult)
