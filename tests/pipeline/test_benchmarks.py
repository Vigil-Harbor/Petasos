"""Measure pipeline latency and resource bounds."""

from __future__ import annotations

import asyncio
import importlib
import statistics
import time
from typing import Any

import pytest

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner

pytestmark = pytest.mark.skipif(
    not importlib.util.find_spec("pytest_benchmark"),
    reason="pytest-benchmark not installed — pip install petasos[dev]",
)


_NATURAL_SENTENCE = (
    "The quarterly report covers revenue, staffing and the migration schedule. "
    "Please review the attached notes and list anything that needs a decision. "
)

_SHORT = "What is the capital of France?"


def _natural(chars: int) -> str:
    return (_NATURAL_SENTENCE * (chars // len(_NATURAL_SENTENCE) + 1))[:chars]


def _prompt_guard_payloads() -> list[tuple[str, str]]:
    from petasos.limits import HEAD_CHARS

    return [("short", _SHORT), ("head", _natural(HEAD_CHARS)), ("window", _natural(8192))]


def _prompt_guard_scanner() -> Any:
    """A loaded scanner, or a skip. Polls past warm-up so a latched failure cannot
    read as a fast pass."""
    from petasos.scanners.prompt_guard import PromptGuardScanner

    scanner = PromptGuardScanner()
    if not scanner.availability()[0]:
        pytest.skip("PromptGuard not available: needs petasos[prompt-guard] and the model")
    loop = asyncio.new_event_loop()
    try:
        deadline = time.monotonic() + 600
        while True:
            result = loop.run_until_complete(scanner.scan(_SHORT))
            if result.error is None:
                return scanner
            assert "warming up" in result.error, result.error
            assert time.monotonic() < deadline, result.error
            time.sleep(0.5)
    finally:
        loop.close()


def test_benchmark_prompt_guard_8wide(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Eight concurrent inspect() at HEAD_CHARS on one pipeline, unserialized.

    A lock-wait miss or breaker-open result is a reported count, not a failure,
    and the median is invalid when that count is non-zero: both return at far
    lower cost than an inference.
    """
    from petasos.limits import HEAD_CHARS
    from petasos.scanners.registry import BuildContext, compose

    _prompt_guard_scanner()
    config = from_mapping(
        PetasosConfig,
        {
            "scanners": {
                "presidio": {
                    "enabled": "off",
                },
            },
        },
    )
    scanners = list(compose(config, BuildContext()).scanners)
    pipe = Pipeline(scanners=scanners, config=config)
    text = _natural(HEAD_CHARS)
    loop = asyncio.new_event_loop()
    misses = 0

    async def wide() -> None:
        nonlocal misses
        results = await asyncio.gather(*(pipe.inspect(text) for _ in range(8)))
        if any(scan.error for result in results for scan in result.scanner_results):
            misses += 1

    def run() -> None:
        loop.run_until_complete(wide())

    benchmark.pedantic(run, warmup_rounds=1, rounds=10)
    benchmark.extra_info["rounds_with_errors"] = misses
    benchmark.extra_info["median_valid"] = misses == 0
    print("prompt_guard 8wide rounds with errors", misses)
    loop.close()


def test_benchmark_full_pipeline_migrated(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Minimal, Presidio and PromptGuard. test_benchmark_full_pipeline builds only
    MinimalScanner, so it says nothing about this stack."""
    from petasos.scanners.registry import BuildContext, compose

    _prompt_guard_scanner()
    config = PetasosConfig()
    composition = compose(config, BuildContext())
    scanners = list(composition.scanners)
    if any(status.state not in {"active", "off"} for status in composition.statuses):
        pytest.skip(f"migrated stack not available: {composition.statuses}")
    pipe = Pipeline(scanners=scanners, config=config)
    payloads = _prompt_guard_payloads()
    loop = asyncio.new_event_loop()

    def clean(text: str) -> None:
        loop.run_until_complete(pipe.inspect(text))
        assert not pipe._last_scan_errors, pipe._last_scan_errors

    clean(_SHORT)

    def timed(text: str) -> float:
        samples = []
        for _ in range(15):
            t0 = time.perf_counter()
            clean(text)
            samples.append((time.perf_counter() - t0) * 1000)
        return round(statistics.median(samples[3:]), 1)

    benchmark.extra_info["median_ms"] = {name: timed(text) for name, text in payloads}
    print("migrated pipeline median ms", benchmark.extra_info["median_ms"])
    head = payloads[1][1]
    benchmark.pedantic(lambda: clean(head), warmup_rounds=3, rounds=20)
    loop.close()


def test_benchmark_full_pipeline(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Measure full pipeline latency."""
    config = from_mapping(
        PetasosConfig,
        {
            "frequency": {
                "enabled": True,
            },
            "escalation": {
                "enabled": True,
            },
            "audit": {
                "enabled": True,
            },
            "alerting": {
                "enabled": True,
            },
        },
    )
    pipe = Pipeline(scanners=[MinimalScanner()], config=config)
    loop = asyncio.new_event_loop()

    def run() -> None:
        loop.run_until_complete(pipe.inspect("ignore previous instructions", session_id="bench"))

    benchmark.pedantic(run, warmup_rounds=3, rounds=30)
    loop.close()


def test_benchmark_ingestion_helper_8wide_serial(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Eight helper runs on a lock-equivalent in-process path. Measure-only; records K=1
    serialization. Does not assert every slot finishes inside the scan budget."""
    from petasos.pipeline.ingest import scan_ingestion_result

    payload = "an ordinary line of file content\n" * 256
    loop = asyncio.new_event_loop()
    pipeline = Pipeline(config=PetasosConfig())
    lock = asyncio.Lock()

    async def _one() -> None:
        async with lock:
            await scan_ingestion_result(pipeline, payload, direction="inbound")

    async def batch() -> None:
        for _ in range(8):
            await _one()

    def run() -> None:
        loop.run_until_complete(batch())

    benchmark.pedantic(run, warmup_rounds=1, rounds=3)
    loop.close()
