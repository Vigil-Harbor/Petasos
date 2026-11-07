"""S7 measurement protocol: failures cannot disappear into successful quantiles."""

import asyncio
import copy
import json
import os
import threading
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
    assert fixtures["sixteen_128k_distinct"]["distinct_fragments"] == 16
    assert fixtures["sixteen_128k_repeated"]["selected_bytes"] == 131072
    assert fixtures["sixteen_128k_distinct"]["payload_bytes"] == 131087
    plan = protocol.case_plan(100)
    assert len(plan) == 17
    assert [c["kind"] for c in plan[:2]] == ["serial", "serial"]
    assert [c["kind"] for c in plan[8:11]] == ["replacement", "preflight", "serial"]
    assert all(c["planned"] == 104 for c in plan if c["kind"] in ("loaded", "replacement"))
    assert len({c["name"] for c in plan}) == len(plan)
    assert protocol.gate_failures(passing_records()) == []


@pytest.mark.parametrize(
    "name,metric,limit",
    [
        ("single_16k", "mean", 1.0),
        ("single_16k", "p95", 1.2),
        ("single_16k", "p99", 1.4),
        ("sixteen_128k_repeated", "mean", 1.8),
        ("sixteen_128k_distinct", "p95", 2.0),
        ("sixteen_128k_distinct", "p99", 2.3),
        ("eight_wide_single_16k_shared_owner_3_3_2", "p95", 5.0),
        ("eight_wide_sixteen_128k_distinct_three_owners_8_0_0", "p95", 7.5),
        ("eight_wide_sixteen_128k_distinct_shared_owner_4_2_2", "max", 8.0),
        ("eight_replacements", "p95", 7.5),
        ("preflight_1m", "p95", 0.05),
    ],
)
def test_each_latency_limit_fails(name: str, metric: str, limit: float) -> None:
    records = passing_records()
    case = records["workloads"][name]
    if metric == "max":
        case["samples"][-1]["seconds"] = limit + 0.01
    else:
        for sample in case["samples"]:
            sample["seconds"] = limit + 0.01
    assert any(f"{name}.{metric}" in f for f in protocol.gate_failures(records))


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
    assert case["samples"][0]["seconds"] >= 0.02
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
    "fixture_name", ["single_16k", "sixteen_128k_repeated", "sixteen_128k_distinct"]
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
async def test_real_loaded_case_records_telemetry_and_closes(tmp_path: Path) -> None:
    _, sources = protocol.fixtures()
    case = {
        **protocol.case_plan(100)[2],
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
