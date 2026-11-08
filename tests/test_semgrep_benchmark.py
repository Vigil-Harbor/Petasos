"""S7 measurement protocol: failures cannot disappear into successful quantiles."""

import asyncio
import copy
import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from petasos._coverage import CoverageSpan, ScanCoverage
from petasos._types import Position, ScanFinding, ScanResult, Severity
from scripts import semgrep_benchmark as bench
from scripts import semgrep_benchmark_protocol as protocol


def passing_records() -> dict[str, Any]:
    records: dict[str, Any] = {"implementation": {"tracked_dirty": False}, "workloads": {}}
    for definition in protocol.case_plan(100):
        case = {**definition, "samples": [], "errors": [], "close": [{"status": "closed"}]}
        for i in range(-1, case["planned"]):
            case["samples"].append(
                {
                    "burst": i // 8,
                    "warmup": i == -1,
                    "status": "ok",
                    "seconds": 0.001,
                    "error": None,
                }
            )
        case["resources"] = {
            "samples": 10,
            "missing": [],
            "root_residue": 0,
            "live_owned_processes": 0,
            "parent_rss_peak_bytes": 1,
            "owned_rss_sampled_peak_bytes": 1,
            "stdout_high_water_per_child_bytes": 1,
            "control_loop_samples": 1,
        }
        records["workloads"][case["name"]] = case
    return records


def expected_result(fixture: dict[str, Any]) -> ScanResult:
    return ScanResult(
        "semgrep",
        tuple(
            ScanFinding(
                rule,
                "unsafe_code",
                Severity.MEDIUM,
                0.8,
                "fixture",
                "semgrep",
                Position(start, end),
                position_basis="original",
            )
            for rule, start, end in fixture["expected_findings"]
        ),
        coverage=ScanCoverage(
            "complete",
            len(fixture["text"]),
            len(fixture["text"]),
            len(fixture["segments"]),
            len(fixture["segments"]),
            tuple(CoverageSpan(a, b, "python", "complete") for a, b in fixture["segments"]),
        ),
    )


def test_pinned_bytes_and_case_plan() -> None:
    manifest, fixtures = protocol.fixtures()
    assert manifest["workload_id"] == protocol.WORKLOAD
    assert fixtures["sixteen_64k_distinct"]["distinct_fragments"] == 16
    assert fixtures["sixteen_64k_repeated"]["selected_bytes"] == 65536
    assert fixtures["sixteen_64k_distinct"]["payload_bytes"] == 65551
    plan = protocol.case_plan(100)
    assert len(plan) == 17
    assert [c["kind"] for c in plan[:2]] == ["serial", "serial"]
    assert [c["kind"] for c in plan[8:11]] == ["replacement", "preflight", "serial"]
    assert all(c["planned"] == 104 for c in plan if c["kind"] in ("loaded", "replacement"))
    assert len({c["name"] for c in plan}) == len(plan)
    assert protocol.gate_failures(passing_records()) == []


LOADED_NAMES = [
    c["name"] for c in protocol.case_plan(100) if c["kind"] in ("loaded", "replacement")
]


def set_seconds(records: dict[str, Any], name: str, seconds: float) -> None:
    for sample in records["workloads"][name]["samples"]:
        sample["seconds"] = seconds


@pytest.mark.parametrize("name", LOADED_NAMES)
def test_every_loaded_row_has_the_deadline_max(name: str) -> None:
    records = passing_records()
    # One long terminal sample leaves p95 unchanged; only the max gate sees it.
    records["workloads"][name]["samples"][-1]["seconds"] = protocol.LOADED_MAX_SECONDS
    assert protocol.gate_failures(records) == []
    records["workloads"][name]["samples"][-1]["seconds"] = protocol.LOADED_MAX_SECONDS + 0.01
    assert any(f.startswith(name + ".max") for f in protocol.gate_failures(records))


@pytest.mark.parametrize(
    "name,reference",
    [
        ("eight_wide_single_16k_shared_owner_4_2_2", "single_16k"),
        ("eight_replacements", "single_16k"),
        ("eight_wide_sixteen_64k_distinct_three_owners_8_0_0", "sixteen_64k_distinct"),
    ],
)
def test_loaded_p95_is_relative_to_the_same_run_serial_mean(name: str, reference: str) -> None:
    records = passing_records()
    set_seconds(records, reference, 0.5)
    set_seconds(records, name, protocol.LOADED_RATIO * 0.5)
    assert protocol.gate_failures(records) == []
    set_seconds(records, name, protocol.LOADED_RATIO * 0.5 + 0.01)
    assert any(f.startswith(name + ".p95") for f in protocol.gate_failures(records))
    # The same absolute latency passes on a host whose serial mean is slower.
    set_seconds(records, reference, 0.51)
    assert protocol.gate_failures(records) == []


@pytest.mark.parametrize("reference", ["single_16k", "sixteen_64k_distinct"])
@pytest.mark.parametrize("breakage", ["absent", "no_successes"])
def test_missing_ratio_reference_fails_closed(reference: str, breakage: str) -> None:
    records = passing_records()
    if breakage == "absent":
        del records["workloads"][reference]
    else:
        for sample in records["workloads"][reference]["samples"]:
            sample["status"] = "error"
    failures = protocol.gate_failures(records)
    dependents = [
        c["name"]
        for c in protocol.case_plan(100)
        if c["name"] in LOADED_NAMES and c["fixture"] == reference
    ]
    assert len(dependents) == (7 if reference == "single_16k" else 6)
    assert all(any(f.startswith(n + ".p95") for f in failures) for n in dependents)


@pytest.mark.parametrize("system", ["Windows", "Darwin", None])
@pytest.mark.parametrize(
    "name,metric",
    [
        ("single_16k", "mean"),
        ("single_16k", "p95"),
        ("single_16k", "p99"),
        ("sixteen_64k_repeated", "mean"),
        ("sixteen_64k_distinct", "p95"),
        ("sixteen_64k_distinct", "p99"),
        ("preflight_1m", "p95"),
    ],
)
def test_each_absolute_limit_fails(system: str | None, name: str, metric: str) -> None:
    records = passing_records()
    if system:
        records["hardware"] = {"system": system}
    limit = (
        protocol.SINGLE_16K_LIMITS_WINDOWS
        if name == "single_16k" and system == "Windows"
        else protocol.SINGLE_16K_LIMITS
        if name == "single_16k"
        else {"p95": 0.05}
        if name == "preflight_1m"
        else protocol.SERIAL_64K_LIMITS
    )[metric]
    # Loaded rows scale with their serial reference, so only this row can fail.
    set_seconds(records, name, limit + 0.01)
    assert any(f.startswith(f"{name}.{metric}") for f in protocol.gate_failures(records))


def test_windows_single_16k_limits_apply_only_on_windows() -> None:
    assert protocol.SINGLE_16K_LIMITS == {"mean": 1.0, "p95": 1.2, "p99": 1.4}
    assert protocol.SINGLE_16K_LIMITS_WINDOWS == {"mean": 1.2, "p95": 1.4, "p99": 1.6}
    for system, passes in (("Windows", True), ("Darwin", False), ("Linux", False), (None, False)):
        records = passing_records()
        if system:
            records["hardware"] = {"system": system}
        set_seconds(records, "single_16k", 1.1)
        assert (protocol.gate_failures(records) == []) is passes, system


@pytest.mark.parametrize(
    "failure", ["error", "missing", "unfinished", "warmup", "close", "resource", "residue"]
)
def test_incomplete_or_error_never_passes(failure: str) -> None:
    records = passing_records()
    case = records["workloads"]["eight_wide_single_16k_shared_owner_3_3_2"]
    if failure == "error":
        case["samples"][-1].update(status="error", error="semgrep.queue_deadline", seconds=0.1)
    elif failure == "missing":
        case["samples"].pop()
    elif failure == "unfinished":
        case["samples"][-1] = {"warmup": False, "burst": 12, "status": "running"}
    elif failure == "warmup":
        case["samples"][0].update(status="error", error="semgrep.engine_error")
    elif failure == "close":
        case["close"][0]["status"] = "failed"
    elif failure == "resource":
        case["resources"]["missing"] = ["owned_rss"]
    else:
        case["resources"]["root_residue"] = 1
    assert protocol.gate_failures(records)
    if failure == "error":
        assert case["counts"]["errored"] == 1
        assert case["successful_seconds"]["runs"] == 103
        assert case["failed_seconds"]["runs"] == 1


def test_finding_and_coverage_mismatch_is_not_clean() -> None:
    _, sources = protocol.fixtures()
    fixture = sources["single_16k"]
    result = expected_result(fixture)
    assert protocol.result_evidence(result, fixture)["error"] is None
    wrong = copy.deepcopy(fixture)
    wrong["expected_findings"][0][1] += 1
    assert protocol.result_evidence(result, wrong)["error"] == "finding_mismatch"
    incomplete = ScanResult("semgrep", result.findings)
    assert protocol.result_evidence(incomplete, fixture)["error"] == "coverage_mismatch"
    assert protocol.result_evidence(None, fixture)["error"] == "invalid_token"


async def test_sibling_errors_and_discard_time_preserved() -> None:
    _, sources = protocol.fixtures()
    fixture = sources["single_16k"]
    result = expected_result(fixture)
    discarded = []

    class Scanner:
        async def prepare(self, *args: Any, **kwargs: Any) -> Any:
            async def discard() -> None:
                await asyncio.sleep(0.02)
                discarded.append(True)

            return SimpleNamespace(consume=lambda *args: result, discard=discard)

    class Broken:
        async def prepare(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("private input/path")

    case: dict[str, Any] = {"distribution": (1, 1, 0), "samples": [], "errors": []}
    await bench.run_burst(case, [Scanner(), Broken(), Scanner()], fixture, 0, False)
    assert len(case["samples"]) == 2
    assert [s["status"] for s in case["samples"]] == ["ok", "error"]
    assert case["samples"][1]["expected_findings"] == 1
    assert case["samples"][1]["observed_findings"] is None
    # Python < 3.13 on Windows backs monotonic() with a ~15.6 ms tick.
    tick = time.get_clock_info("monotonic").resolution
    assert case["samples"][0]["seconds"] >= 0.02 - tick
    assert discarded == [True]
    assert "private" not in json.dumps(case)


async def test_cancellation_records_terminal_and_discards() -> None:
    started = asyncio.Event()
    cleaned = asyncio.Event()

    class Scanner:
        async def prepare(self, *args: Any, **kwargs: Any) -> Any:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

    _, sources = protocol.fixtures()
    row: dict[str, Any] = {"warmup": False, "burst": 0}
    task = asyncio.create_task(bench.scan_sample(Scanner(), sources["single_16k"], row))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert cleaned.is_set()
    assert row["error"] == "caller_cancelled"
    assert row["status"] == "error" and row["seconds"] >= 0


async def test_discard_failure_preserves_original_error() -> None:
    _, sources = protocol.fixtures()

    async def discard() -> None:
        raise RuntimeError("private details")

    class Scanner:
        async def prepare(self, *args: Any, **kwargs: Any) -> Any:
            return SimpleNamespace(
                consume=lambda *args: ScanResult("semgrep", (), error="semgrep.queue_deadline"),
                discard=discard,
            )

    row: dict[str, Any] = {}
    await bench.scan_sample(Scanner(), sources["single_16k"], row)
    assert row["error"] == "semgrep.queue_deadline"
    assert row["discard_error"] == "discard_RuntimeError"
    assert row["status"] == "error"


def test_stage_timings_instrument_owned_root_removal(tmp_path: Path) -> None:
    # Regression for PET-255: root_remove_attempt wraps marker-last removal.
    from contextlib import ExitStack

    root = tmp_path / "psg-owned00"
    root.mkdir()
    (root / "petasos-owner.json").write_text("{}", encoding="utf-8")
    (root / "note.txt").write_text("x", encoding="utf-8")
    stages = bench.StageTimings()
    with ExitStack() as stack:
        stages.install(stack)
        from petasos.scanners._semgrep_roots import remove_owned_root

        remove_owned_root(root)
    assert stages.values["root_remove_attempt"]
    assert not root.exists()


async def test_recorder_checkpoint_includes_cleanup_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections import deque

    from petasos.scanners import _semgrep_runtime as runtime

    holder = SimpleNamespace(
        lock=threading.Lock(),
        cleanup_diagnostics=deque(["kind=recovery outcome=recovered"]),
    )
    monkeypatch.setattr(runtime, "_RUNTIME", holder)
    records: dict[str, Any] = {}
    recorder = bench.Recorder(tmp_path / "out.json", records, bench.StageTimings())
    await recorder.save()
    assert records["cleanup_diagnostics"] == ["kind=recovery outcome=recovered"]


def test_checkpoint_atomic_and_lf(tmp_path: Path) -> None:
    path = tmp_path / "partial.json"
    protocol.checkpoint(path, json.dumps({"unfinished": 8}, indent=2))
    assert b"\r" not in path.read_bytes()
    assert json.loads(path.read_bytes()) == {"unfinished": 8}
    assert not path.with_name(path.name + ".tmp").exists()


async def test_canceled_checkpoint_finishes_before_final_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    writes: list[int] = []

    def blocked_write(path: Path, snapshot: str) -> None:
        if not writes:
            entered.set()
            assert release.wait(2)
        writes.append(json.loads(snapshot)["value"])

    monkeypatch.setattr(bench, "checkpoint", blocked_write)
    records: dict[str, Any] = {"value": 1}
    recorder = bench.Recorder(tmp_path / "output.json", records, bench.StageTimings())
    first = asyncio.create_task(recorder.save())
    assert await asyncio.to_thread(entered.wait, 1)
    first.cancel()
    records["value"] = 2
    second = asyncio.create_task(recorder.save())
    await asyncio.sleep(0)
    assert not second.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(first, 2)
    await asyncio.wait_for(second, 2)
    assert writes == [1, 2]


def test_monitor_snapshots_source_reference_once() -> None:
    pytest.importorskip("psutil")
    from scripts.semgrep_benchmark_resources import Resources

    class Job:
        child = None
        selection = None
        reads = 0

        @property
        def source(self) -> Any:
            self.reads += 1
            return ("abc", None, None) if self.reads == 1 else None

    job = Job()
    runtime = SimpleNamespace(
        lock=threading.Lock(),
        active=[job],
        pending={},
        thread=SimpleNamespace(is_alive=lambda: False),
    )
    monitor = Resources(runtime)
    monitor._sample()
    assert job.reads == 1
    assert monitor.data["source_characters_sampled_peak"] == 3


@pytest.mark.parametrize("closed", [True, False])
def test_monitor_closing_loop_is_not_missing_telemetry(closed: bool) -> None:
    pytest.importorskip("psutil")
    from scripts.semgrep_benchmark_resources import Resources

    def closing(callback: Any) -> None:
        raise RuntimeError("closed loop")

    runtime = SimpleNamespace(
        lock=threading.Lock(),
        active=[],
        pending={},
        thread=SimpleNamespace(is_alive=lambda: True),
        loop=SimpleNamespace(call_soon_threadsafe=closing, is_closed=lambda: closed),
    )
    monitor = Resources(runtime)
    if closed:
        monitor._sample()
        assert not monitor.data["missing"]
    else:
        with pytest.raises(RuntimeError):
            monitor._sample()
    assert not monitor.probe_pending.is_set()


@pytest.mark.parametrize("cancel_count", [0, 1, 2])
async def test_case_close_finishes_after_cancellation_and_stops_failed_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel_count: int,
) -> None:
    from petasos.scanners._semgrep_runtime import SemgrepCloseResult

    entered = asyncio.Event()
    release = asyncio.Event()
    events: list[str] = []
    runtime = SimpleNamespace(lock=threading.Lock(), failed=False)

    class Owner:
        async def __aenter__(self) -> Any:
            return self

        async def aclose(self, **kwargs: Any) -> SemgrepCloseResult:
            events.append("close_started")
            entered.set()
            await release.wait()
            events.append("closed")
            return SemgrepCloseResult("closed")

    class Scanner:
        def __init__(self, **kwargs: Any) -> None:
            self._lease = SimpleNamespace(runtime=runtime)

        def availability(self) -> tuple[bool, None]:
            return True, None

    class Monitor:
        def __init__(self, runtime: Any) -> None:
            pass

        def install(self, stack: Any) -> None:
            stack.callback(events.append, "patches_restored")

        def finish(self) -> dict[str, Any]:
            events.append("monitor_stopped")
            return {}

    async def burst(case: dict[str, Any], *args: Any) -> None:
        case["samples"].append({"burst": -1, "warmup": True, "status": "ok", "seconds": 0.01})
        runtime.failed = True

    monkeypatch.setattr(bench, "SemgrepLifecycleOwner", Owner)
    monkeypatch.setattr(bench, "SemgrepScanner", Scanner)
    monkeypatch.setattr(bench, "Resources", Monitor)
    monkeypatch.setattr(bench, "run_burst", burst)
    _, sources = protocol.fixtures()
    case = {**protocol.case_plan(100)[2], "samples": [], "errors": []}
    recorder = bench.Recorder(tmp_path / "partial.json", {"workloads": {}}, bench.StageTimings())
    task = asyncio.create_task(bench.run_case(case, sources, "unused", "unused", recorder))
    await asyncio.wait_for(entered.wait(), 1)
    for _ in range(cancel_count):
        task.cancel()
        await asyncio.sleep(0)
    assert not task.done()
    release.set()
    if cancel_count:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
    else:
        assert not await asyncio.wait_for(task, 2)  # failed runtime, despite successful close
    assert events == ["close_started", "closed", "monitor_stopped", "patches_restored"]
    assert case["close"][0]["status"] == "closed"
    assert "runtime_failed" in case["errors"]
    assert case["counts"]["not_run"] == case["planned"]


async def test_wall_budget_preserves_partial_failure_and_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleaned = asyncio.Event()

    async def stalled(runs: int, records: dict[str, Any], recorder: Any) -> None:
        records.update(passing_records())
        records["workloads"]["single_16k"]["samples"].pop()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    monkeypatch.setattr(bench, "measure", stalled)
    monkeypatch.setattr(bench, "MEASUREMENT_BUDGET_SECONDS", 0.02)
    output = tmp_path / "partial.json"
    result = await bench.run_measurement(100, output, bench.StageTimings())
    assert cleaned.is_set()
    assert result["measurement_error"] == "TimeoutError"
    assert result["gate_failures"] and not result["component_gates_passed"]
    assert json.loads(output.read_bytes())["workloads"]["single_16k"]["counts"]["not_run"] == 1


@pytest.mark.skipif(not os.environ.get("SEMGREP_ENGINE_PATH"), reason="real engine not configured")
@pytest.mark.parametrize(
    "fixture_name", ["single_16k", "sixteen_64k_repeated", "sixteen_64k_distinct"]
)
async def test_real_fixture_finding_and_coverage_contract(fixture_name: str) -> None:
    """A first-run mismatch fails; never rewrite expected findings to match it."""
    from petasos.scanners.semgrep import SemgrepLifecycleOwner, SemgrepScanner

    _, fixtures = protocol.fixtures()
    async with SemgrepLifecycleOwner() as owner:
        scanner = SemgrepScanner(
            owner=owner,
            engine_path=os.environ["SEMGREP_ENGINE_PATH"],
            engine_sha256=os.environ["SEMGREP_ENGINE_SHA256"],
        )
        async with asyncio.timeout(12):
            while scanner.availability()[1] == "semgrep.probe_pending":
                await asyncio.sleep(0.01)
        assert scanner.availability()[0]
        row: dict[str, Any] = {"warmup": False, "burst": 0}
        await bench.scan_sample(scanner, fixtures[fixture_name], row)
        assert row["status"] == "ok", row


@pytest.mark.skipif(not os.environ.get("SEMGREP_ENGINE_PATH"), reason="real engine not configured")
@pytest.mark.parametrize("plan_index", [2, 5, 8])
async def test_real_loaded_case_records_telemetry_and_closes(
    tmp_path: Path, plan_index: int
) -> None:
    _, sources = protocol.fixtures()
    case = {
        **protocol.case_plan(100)[plan_index],
        "planned": 8,
        "bursts": 1,
        "samples": [],
        "errors": [],
    }
    records = {"workloads": {case["name"]: case}}
    recorder = bench.Recorder(tmp_path / "partial.json", records, bench.StageTimings())
    clean = await bench.run_case(
        case,
        sources,
        os.environ["SEMGREP_ENGINE_PATH"],
        os.environ["SEMGREP_ENGINE_SHA256"],
        recorder,
    )
    assert clean
    assert case["counts"]["completed"] == 8
    assert not case["counts"]["errored"], case["samples"]
    resources = case["resources"]
    assert not resources["missing"], resources
    assert resources["samples"] > 0
    assert resources["parent_rss_peak_bytes"] > 0
    assert resources["owned_rss_sampled_peak_bytes"] > 0
    assert resources["stdout_high_water_per_child_bytes"] > 0
    assert resources["control_loop_samples"] > 0
    assert resources["root_residue"] == resources["live_owned_processes"] == 0
    assert not any(resources["runtime_residuals"].values())
