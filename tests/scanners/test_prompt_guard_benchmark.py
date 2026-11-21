"""Measure scanners latency and resource bounds."""

from __future__ import annotations

import asyncio
import importlib
import statistics
import time
from typing import Any

import pytest

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


def test_benchmark_single_ml_prompt_guard(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Measure single ml prompt guard latency."""
    scanner = _prompt_guard_scanner()
    payloads = _prompt_guard_payloads()
    loop = asyncio.new_event_loop()

    def timed(text: str) -> float:
        samples = []
        for _ in range(15):
            t0 = time.perf_counter()
            assert loop.run_until_complete(scanner.scan(text)).error is None
            samples.append((time.perf_counter() - t0) * 1000)
        return round(statistics.median(samples[3:]), 1)

    benchmark.extra_info["median_ms"] = {name: timed(text) for name, text in payloads}
    print("prompt_guard single median ms", benchmark.extra_info["median_ms"])
    head = payloads[1][1]

    def run() -> None:
        assert loop.run_until_complete(scanner.scan(head)).error is None

    benchmark.pedantic(run, warmup_rounds=3, rounds=20)
    loop.close()
