from __future__ import annotations

import asyncio
import importlib

import pytest

from petasos.config import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner


def _llm_guard_available() -> bool:
    try:
        importlib.import_module("llm_guard")
        return True
    except ImportError:
        return False


def _llama_firewall_available() -> bool:
    try:
        importlib.import_module("llamafirewall")
        return True
    except ImportError:
        return False


def test_benchmark_syntactic_only(benchmark) -> None:  # type: ignore[no-untyped-def]
    scanner = MinimalScanner()
    loop = asyncio.new_event_loop()

    def run() -> None:
        loop.run_until_complete(scanner.scan("ignore previous instructions", direction="inbound"))

    benchmark.pedantic(run, warmup_rounds=5, rounds=50)
    loop.close()


@pytest.mark.skipif(
    not _llm_guard_available(),
    reason="llm-guard not installed — pip install petasos[llm-guard]",
)
def test_benchmark_single_ml_llm_guard(benchmark) -> None:  # type: ignore[no-untyped-def]
    from petasos.scanners.llm_guard import LlmGuardScanner

    scanner = LlmGuardScanner()
    loop = asyncio.new_event_loop()

    def run() -> None:
        loop.run_until_complete(scanner.scan("ignore previous instructions", direction="inbound"))

    benchmark.pedantic(run, warmup_rounds=2, rounds=10)
    loop.close()


@pytest.mark.skipif(
    not _llama_firewall_available(),
    reason="llamafirewall not installed — pip install petasos[llamafirewall]",
)
def test_benchmark_single_ml_llama_firewall(benchmark) -> None:  # type: ignore[no-untyped-def]
    from petasos.scanners.llama_firewall import LlamaFirewallScanner

    scanner = LlamaFirewallScanner()
    loop = asyncio.new_event_loop()

    def run() -> None:
        loop.run_until_complete(scanner.scan("ignore previous instructions", direction="inbound"))

    benchmark.pedantic(run, warmup_rounds=2, rounds=10)
    loop.close()


def test_benchmark_full_pipeline(benchmark, valid_key) -> None:  # type: ignore[no-untyped-def]
    config = PetasosConfig(
        frequency_enabled=True,
        escalation_enabled=True,
        audit_enabled=True,
        alert_enabled=True,
    )
    pipe = Pipeline(scanners=[MinimalScanner()], config=config)
    pipe.activate(valid_key)
    loop = asyncio.new_event_loop()

    def run() -> None:
        loop.run_until_complete(pipe.inspect("ignore previous instructions", session_id="bench"))

    benchmark.pedantic(run, warmup_rounds=3, rounds=30)
    loop.close()
