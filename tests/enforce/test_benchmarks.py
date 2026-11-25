"""Measure enforce latency and resource bounds."""

from __future__ import annotations

import asyncio
import importlib
import tempfile
from pathlib import Path

import pytest

from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.enforce import Enforcer, HostInfo, ToolCall
from petasos.enforce.types import InitGate, SettingsSnapshot
from petasos.pipeline import Pipeline

pytestmark = pytest.mark.skipif(
    not importlib.util.find_spec("pytest_benchmark"),
    reason="pytest-benchmark not installed — pip install petasos[dev]",
)

# See docs/architecture/rationale.md, "Test timing and backend qualification".


def _bench_enforcer(
    directory: Path, *, armed: bool = True, init: InitGate | None = None
) -> Enforcer:
    """An enforcer that has finished starting, armed or not."""
    snapshot = SettingsSnapshot(armed=armed, config=PetasosConfig(), secrets=Secrets(), token=1)

    enforcer = Enforcer(
        lambda: snapshot,
        host=HostInfo(subagent_hooks=False),
        init=init,
        spool_path=str(directory / "events.jsonl"),
    )
    enforcer.start()
    enforcer.settle(30)
    return enforcer


def _ingestion_case(  # type: ignore[no-untyped-def]
    benchmark, payload: str, *, tool: str = "read_file", armed: bool = True
) -> None:
    directory = Path(tempfile.mkdtemp())
    enforcer = _bench_enforcer(directory, armed=armed)
    call = ToolCall(tool=tool, session="bench")

    def run() -> None:
        enforcer.tool_result(call, payload)

    try:
        benchmark.pedantic(run, warmup_rounds=3, rounds=20)
    finally:
        enforcer.close()


def test_benchmark_ingestion_result_1kb(benchmark) -> None:  # type: ignore[no-untyped-def]
    """1 KB: well inside the window, so the whole result is scanned and no clipping runs."""
    _ingestion_case(benchmark, "an ordinary line of file content\n" * 32)


def test_benchmark_ingestion_result_8kb(benchmark) -> None:  # type: ignore[no-untyped-def]
    """8 KB: still the serial-curve first point. Head inspect plus one syntactic chunk."""
    _ingestion_case(benchmark, "an ordinary line of file content\n" * 256)


def test_benchmark_ingestion_result_8kb_armed_correlator(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Measure ingestion result 8kb armed correlator latency.

    See docs/architecture/rationale.md, "Test timing and backend qualification"."""
    _ingestion_case(benchmark, "an ordinary line of file content\n" * 256)


def test_benchmark_ingestion_result_8wide_concurrent(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Measure ingestion result 8wide concurrent latency.

    See docs/architecture/rationale.md, "Test timing and backend qualification"."""
    from petasos.limits import HEAD_CHARS

    payload = "x" * HEAD_CHARS
    loop = asyncio.new_event_loop()
    pipeline = Pipeline(config=PetasosConfig())

    async def batch() -> None:
        await asyncio.gather(*[pipeline.inspect(payload, direction="inbound") for _ in range(8)])

    def run() -> None:
        loop.run_until_complete(batch())

    benchmark.pedantic(run, warmup_rounds=1, rounds=5)
    loop.close()


def test_benchmark_ingestion_result_100kb(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Measure ingestion result 100kb latency."""
    _ingestion_case(benchmark, "an ordinary line of file content\n" * 3_200)


def test_benchmark_ingestion_result_1e6(benchmark) -> None:  # type: ignore[no-untyped-def]
    """1,000,000 characters: ceiling-inclusive full coverage (head inspect + 18 chunks)."""
    _ingestion_case(benchmark, "x" * 1_000_000)


def test_benchmark_ingestion_non_ingestion_tool_large_result(benchmark) -> None:  # type: ignore[no-untyped-def]
    """An excluded tool with a large result: gate 3 returns before any scan or clip, so
    this is the cost the hook adds to every excluded call. It should be negligible."""
    _ingestion_case(benchmark, "x" * 100_000, tool="write_file")


def test_benchmark_ingestion_unknown_tool_8kb(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Measure ingestion unknown tool 8kb latency."""
    _ingestion_case(
        benchmark,
        "an ordinary line of file content\n" * 256,
        tool="definitely_not_a_registered_tool",
    )


def test_benchmark_ingestion_disarmed_no_op(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Measure ingestion disarmed no op latency."""
    _ingestion_case(benchmark, "x" * 100_000, armed=False)


def test_benchmark_fallback_param_scan_1mb(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Measure fallback param scan 1mb latency.

    See docs/architecture/rationale.md, "Test timing and backend qualification"."""
    from petasos.guard.params import _MAX_PARAM_TEXT_LEN

    directory = Path(tempfile.mkdtemp())
    enforcer = _bench_enforcer(directory, init=InitGate.failed("bench"))
    call = ToolCall(tool="write_file", args={"data": "x" * _MAX_PARAM_TEXT_LEN}, session="s1")

    def run() -> None:
        enforcer.tool_call(call)

    try:
        benchmark.pedantic(run, rounds=3, iterations=1)
    finally:
        enforcer.close()
