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

# ---------------------------------------------------------------------------
# PET-170: the ingestion path (transform_tool_result). Decision 8 evidence.
# ---------------------------------------------------------------------------
#
# Measure-only under the module-level skipif, for the same reason as every benchmark
# above: shared CI runners are too slow and noisy for a wall-clock assertion. The budget
# these numbers are read against is stated in CLAUDE.md (12 ms of scan at the 8,000-char
# cap; ~15 ms end to end), and the correctness of the clipping that keeps the input inside
# that cap is pinned by tests/enforce_parity/test_enforce_parity.py
# test_enforcer_matches_record[tool-result-oversized].


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
    """PET-176 re-measure: the same 8 KB case with the correlator and cap LIVE.

    The pre-PET-176 figures were taken with session_id=None, which short-circuited
    _frequency_hook (an RLock acquisition plus the Step-1 TTL drain), _escalation_hook,
    two session-keyed alert rules, and session-bearing audit rows. D6 arms all of them,
    so the CLAUDE.md 12 ms budget is re-measured here rather than asserted; record the
    measured headroom in the PR.
    """
    _ingestion_case(benchmark, "an ordinary line of file content\n" * 256)


def test_benchmark_ingestion_result_8wide_concurrent(benchmark) -> None:  # type: ignore[no-untyped-def]
    """PET-179 Decision 5: 8 concurrent head-sized inspect() calls on a base install.

    K=1 helper serialization is a different axis (see
    ``test_benchmark_ingestion_helper_8wide_serial``). This gathers eight
    ``inspect()`` calls at ``HEAD_CHARS`` so the CLAUDE.md 8-wide overrun has an
    in-repo anchor. Measure-only.
    """
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
    """100 KB: no longer flat against 8 KB; the syntactic sweep now covers the whole result."""
    _ingestion_case(benchmark, "an ordinary line of file content\n" * 3_200)


def test_benchmark_ingestion_result_1e6(benchmark) -> None:  # type: ignore[no-untyped-def]
    """1,000,000 characters: ceiling-inclusive full coverage (head inspect + 18 chunks)."""
    _ingestion_case(benchmark, "x" * 1_000_000)


def test_benchmark_ingestion_non_ingestion_tool_large_result(benchmark) -> None:  # type: ignore[no-untyped-def]
    """An excluded tool with a large result: gate 3 returns before any scan or clip, so
    this is the cost the hook adds to every excluded call. It should be negligible."""
    _ingestion_case(benchmark, "x" * 100_000, tool="write_file")


def test_benchmark_ingestion_unknown_tool_8kb(benchmark) -> None:  # type: ignore[no-untyped-def]
    """PET-181: unknown-tool cap-window case. Same payload as the 8 KB read_file
    case. K=1 (one petasos-async loop); shed rate 0 by construction; capacity
    1/S; P=8 is measured (see 8-wide concurrent); P=80 is a PET-178 residual.
    """
    _ingestion_case(
        benchmark,
        "an ordinary line of file content\n" * 256,
        tool="definitely_not_a_registered_tool",
    )


def test_benchmark_ingestion_disarmed_no_op(benchmark) -> None:  # type: ignore[no-untyped-def]
    """The PET-111 disarm gate, above everything else: zero added scan cost while
    Unequipped, which is the invariant the whole disarm design rests on."""
    _ingestion_case(benchmark, "x" * 100_000, armed=False)


def test_benchmark_fallback_param_scan_1mb(benchmark) -> None:  # type: ignore[no-untyped-def]
    """PET-190 T-8, measure-only: a full-cap parameter scan on the failed-init fallback.

    Driven through the plugin's real ``_run_async``, so the number is the loop-blocked
    duration a queued call inherits, not the scan in isolation. ``MinimalScanner.scan`` has
    no await point, so once scheduled it runs to completion and the 15 s timeout bounds only
    the caller's wait. ``pedantic`` with 3 rounds: the default calibration would spend
    minutes of wall clock on a 1 MB scan. No assertion; the recorded figure is the artifact.
    """
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
