"""Opt-in component measurements; never a substitute for real-host qualification."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import inspect
import json
import os
import platform
import shutil
import subprocess
import threading
import time
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import asdict
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
from unittest.mock import patch

from petasos.scanners._semgrep_source import preflight
from petasos.scanners.semgrep import SemgrepLifecycleOwner, SemgrepScanner
from scripts.semgrep_benchmark_protocol import (
    MANIFEST_SHA256,
    WORKLOAD,
    case_plan,
    checkpoint,
    finish_case,
    fixtures,
    gate_failures,
    result_evidence,
    summary,
)
from scripts.semgrep_benchmark_resources import Resources

MEASUREMENT_BUDGET_SECONDS = 35 * 60


class StageTimings:
    """Benchmark-only wrappers; store durations, never arguments/source text."""

    def __init__(self) -> None:
        self.values: dict[str, list[float]] = defaultdict(list)
        self.errors: list[dict[str, str | int | None]] = []
        self.error_count = 0
        self.lock = threading.Lock()

    def wrap(self, name: str, function: Callable[..., Any]) -> Callable[..., Any]:
        def record_error(exc: Exception) -> None:
            # Never retain messages, filenames, arguments or submitted text.
            # Keep the earliest failures before retry/close errors obscure them.
            with self.lock:
                self.error_count += 1
                if len(self.errors) < 64:
                    self.errors.append(
                        {
                            "stage": name,
                            "type": type(exc).__name__,
                            "errno": exc.errno if isinstance(exc, OSError) else None,
                            "winerror": getattr(exc, "winerror", None)
                            if isinstance(exc, OSError)
                            else None,
                        }
                    )

        def record(start: float) -> None:
            with self.lock:
                self.values[name].append(time.monotonic() - start)

        if inspect.iscoroutinefunction(function):

            @wraps(function)
            async def asynchronous(*args: Any, **kwargs: Any) -> Any:
                started = time.monotonic()
                try:
                    return await function(*args, **kwargs)
                except Exception as exc:
                    record_error(exc)
                    raise
                finally:
                    record(started)

            return asynchronous

        @wraps(function)
        def synchronous(*args: Any, **kwargs: Any) -> Any:
            started = time.monotonic()
            try:
                return function(*args, **kwargs)
            except Exception as exc:
                record_error(exc)
                raise
            finally:
                record(started)

        return synchronous

    def install(self, stack: ExitStack) -> None:
        from petasos.scanners import _semgrep_engine as engine
        from petasos.scanners import _semgrep_process as process
        from petasos.scanners import _semgrep_runtime as runtime

        child = process._WindowsChild if os.name == "nt" else process._PosixChild
        for owner, attribute, stage in (
            (runtime.Runtime, "_verify_identity", "identity"),
            (runtime.Runtime, "_new_root", "root_creation"),
            (runtime, "select_sources", "projection"),
            (runtime, "remove_root", "root_cleanup"),
            (shutil, "rmtree", "root_remove_attempt"),
            (engine, "scan_selected", "engine_scan"),
            (runtime, "scan_selected", "engine_scan"),
            (engine, "strict_output", "output_decode"),
            (engine, "_local_functions", "python_postfilter"),
            (engine, "run_process", "child_total"),
            (child, "__init__", "spawn"),
            (child, "poll", "poll"),
            (child, "read", "pipe_read"),
            (child, "terminate", "terminate"),
            (child, "cleaned", "reap_check"),
        ):
            stack.enter_context(
                patch.object(owner, attribute, self.wrap(stage, getattr(owner, attribute)))
            )


def revision() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]

    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()

    return {
        "commit": git("rev-parse", "HEAD"),
        "tracked_dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
        "python_version": platform.python_version(),
        "petasos_version": importlib.metadata.version("petasos"),
        "runner_image": os.environ.get("ImageOS", "local"),  # noqa: SIM112 (GitHub runner spelling)
        "runner_image_version": os.environ.get("ImageVersion", "local"),  # noqa: SIM112
    }


class Recorder:
    def __init__(self, output: Path, records: dict[str, Any], stages: StageTimings) -> None:
        self.output = output
        self.records = records
        self.stages = stages
        self.lock = asyncio.Lock()

    async def save(self) -> None:
        async with self.lock:
            for case in self.records.get("workloads", {}).values():
                finish_case(case)
            with self.stages.lock:
                self.records["stage_durations_seconds"] = {
                    name: summary(values) for name, values in self.stages.values.items()
                }
                self.records["stage_errors"] = list(self.stages.errors)
                self.records["stage_error_count"] = self.stages.error_count
            snapshot = json.dumps(self.records, indent=2, allow_nan=False)
            writer = asyncio.create_task(asyncio.to_thread(checkpoint, self.output, snapshot))
            try:
                await asyncio.shield(writer)
            except asyncio.CancelledError:
                # Canceling a to_thread await does not stop its writer. Keep the
                # single-writer lock until it settles, before the final save.
                await writer
                raise

    async def periodic(self) -> None:
        while True:
            await asyncio.sleep(30)
            await self.save()


async def scan_sample(scanner: Any, fixture: dict[str, Any], row: dict[str, Any]) -> None:
    started = time.monotonic()
    row.update(
        expected_findings=len(fixture["expected_findings"]),
        expected_targets=len(fixture["segments"]),
        observed_findings=None,
        completed_targets=None,
    )
    token = None
    try:
        token = await scanner.prepare(
            fixture["text"],
            binding=scanner,
            segments=tuple(tuple(s) for s in fixture["segments"]),
        )
        result = token.consume(scanner, fixture["text"])
        row.update(result_evidence(result, fixture))
    except asyncio.CancelledError:
        row["error"] = "caller_cancelled"
        raise
    except Exception as exc:
        row["error"] = "exception_" + type(exc).__name__
    finally:
        try:
            if token is not None:
                await token.discard()
        except asyncio.CancelledError:
            row["error"] = "discard_cancelled"
            raise
        except Exception as exc:
            row["error"] = "discard_" + type(exc).__name__
        finally:
            row["seconds"] = time.monotonic() - started
            row["status"] = "error" if row.get("error") else "ok"


async def run_burst(
    case: dict[str, Any],
    scanners: list[Any],
    fixture: dict[str, Any],
    burst: int,
    warmup: bool,
) -> None:
    samples = []
    distribution = case.get("distribution", (1, 0, 0))
    for index, count in enumerate(distribution):
        for _ in range(count):
            row = {"burst": burst, "warmup": warmup, "key": index, "status": "running"}
            case["samples"].append(row)
            samples.append(scan_sample(scanners[index], fixture, row))
    # scan_sample accounts for each error before gather returns. Cancellation
    # still propagates to every owned preparation and its finally/discard.
    outcomes = await asyncio.gather(*samples, return_exceptions=True)
    if any(isinstance(x, BaseException) for x in outcomes):
        case["errors"].append("sample_exception")


async def replacements(
    case: dict[str, Any],
    scanners: list[Any],
    fixture: dict[str, Any],
    burst: int,
    warmup: bool,
) -> None:
    scanner = scanners[0]
    lease = scanner._lease
    assert lease is not None
    active = [asyncio.create_task(scanner.scan(fixture["text"])) for _ in range(2)]
    fault = {"burst": burst, "warmup": warmup, "active_reached": False}
    case.setdefault("fault_cycles", []).append(fault)
    try:
        until = time.monotonic() + 2
        while time.monotonic() < until:
            with lease.runtime.lock:
                if len(lease.runtime.active) == 2:
                    fault["active_reached"] = True
                    break
            await asyncio.sleep(0.001)
        if not fault["active_reached"]:
            case["errors"].append("replacement_not_active")
            return
        for task in active:
            task.cancel()
        await run_burst(case, scanners, fixture, burst, warmup)
    finally:
        for task in active:
            if not task.done():
                task.cancel()
        outcomes = await asyncio.gather(*active, return_exceptions=True)
        fault["cancelled"] = sum(isinstance(x, asyncio.CancelledError) for x in outcomes)
        if fault["cancelled"] != 2:
            case["errors"].append("replacement_not_cancelled")


async def run_case(
    case: dict[str, Any],
    sources: dict[str, Any],
    engine: str,
    digest: str,
    recorder: Recorder,
) -> bool:
    owners: list[SemgrepLifecycleOwner] = []
    monitor = None
    stack = ExitStack()
    try:
        if case["kind"] == "preflight":
            for index in range(-1, case["planned"]):
                row = {"warmup": index == -1, "burst": index, "status": "running"}
                case["samples"].append(row)
                started = time.monotonic()
                try:
                    if await preflight("benign words " * 76923):
                        row["error"] = "preflight_not_empty"
                except asyncio.CancelledError:
                    row["error"] = "caller_cancelled"
                    raise
                finally:
                    row["seconds"] = time.monotonic() - started
                    row["status"] = "error" if row.get("error") else "ok"
            return True
        cold = time.monotonic()
        for _ in range(3 if case.get("topology") == "three_owners" else 1):
            owner = SemgrepLifecycleOwner()
            await owner.__aenter__()
            owners.append(owner)
        scanners = [
            SemgrepScanner(
                owner=owners[index] if len(owners) == 3 else owners[0],
                engine_path=engine,
                engine_sha256=digest,
                semgrep_scheduling_key=object(),
            )
            for index in range(3)
        ]
        until = time.monotonic() + 8
        while (
            scanners[0].availability()[1] == "semgrep.probe_pending" and time.monotonic() < until
        ):
            await asyncio.sleep(0.01)
        case["cold_probe_seconds"] = time.monotonic() - cold
        if not all(s.availability()[0] for s in scanners):
            case["errors"].append("probe_unavailable")
            return False
        runtime = scanners[0]._lease.runtime  # type: ignore[union-attr]
        if case["kind"] in ("loaded", "replacement"):
            monitor = Resources(runtime)
            monitor.install(stack)
        fixture = sources[case["fixture"]]
        case["payload_sha256"] = fixture["payload_sha256"]
        iterations = case.get("bursts", case["planned"])
        for burst in range(-1, iterations):
            if case["kind"] == "replacement":
                await replacements(case, scanners, fixture, burst, burst == -1)
            else:
                await run_burst(case, scanners, fixture, burst, burst == -1)
            if case["kind"] != "serial":
                await recorder.save()
            if burst == -1 and (
                case["errors"] or any(s["status"] != "ok" for s in case["samples"])
            ):
                case["errors"].append("warmup_failed")
                break
            with runtime.lock:
                failed = runtime.failed
            if failed:
                case["errors"].append("runtime_failed")
                break
    except asyncio.CancelledError:
        case["errors"].append("measurement_cancelled")
        raise
    except Exception as exc:
        case["errors"].append("exception_" + type(exc).__name__)
    finally:
        deadline = time.monotonic() + 3
        closed = await asyncio.gather(
            *(o.aclose(deadline=deadline) for o in owners),
            return_exceptions=True,
        )
        case["close"] = [
            asdict(c)
            if not isinstance(c, BaseException)
            else {"status": "exception", "type": type(c).__name__}
            for c in closed
        ]
        try:
            if monitor is not None:
                case["resources"] = await asyncio.to_thread(monitor.finish)
                case["resources"]["limit_errors"] = [
                    s["error"]
                    for s in case["samples"]
                    if s.get("error")
                    in ("semgrep.memory_limit", "semgrep.output_limit", "semgrep.engine_error")
                ]
        finally:
            stack.close()
        finish_case(case)
    return bool(case["close"]) and all(c["status"] == "closed" for c in case["close"])


async def measure(runs: int, records: dict[str, Any], recorder: Recorder) -> None:
    import psutil

    manifest, sources = fixtures()
    cpu = platform.processor() or "unavailable"
    if platform.system() == "Darwin":
        try:
            cpu = (
                subprocess.check_output(
                    ["sysctl", "-n", "machdep.cpu.brand_string"],
                    text=True,
                    timeout=2,
                ).strip()
                or "unavailable"
            )
        except (OSError, subprocess.SubprocessError):
            cpu = "unavailable"
    records.update(
        {
            "schema_version": 2,
            "workload": WORKLOAD,
            "criteria_version": "S7-2026-11-07-v2",
            "fixture_manifest_sha256": MANIFEST_SHA256,
            "fixtures": manifest,
            "implementation": revision(),
            "engine_version": "1.183.0",
            "hardware": {
                "architecture": platform.machine(),
                "os": platform.platform(),
                "cpu": cpu,
                "logical_cores": os.cpu_count(),
                "physical_cores": psutil.cpu_count(logical=False),
                "ram_bytes": psutil.virtual_memory().total,
                "runner_label": os.environ.get("PETASOS_BENCHMARK_RUNNER", "local"),
            },
            "workloads": {c["name"]: {**c, "samples": [], "errors": []} for c in case_plan(runs)},
            "gate_failures": ["measurement in progress"],
        }
    )
    engine = os.environ["SEMGREP_ENGINE_PATH"]
    with open(engine, "rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    records["engine_sha256"] = digest
    rules = Path(__file__).resolve().parents[1] / "petasos/scanners/semgrep_rules/rules.json"
    records["rules_sha256"] = hashlib.sha256(rules.read_bytes()).hexdigest()
    await recorder.save()
    for case in records["workloads"].values():
        clean = await run_case(case, sources, engine, digest, recorder)
        await recorder.save()
        print(case["name"], json.dumps(case["successful_seconds"]), flush=True)
        if not clean:
            records["measurement_error"] = "owner_or_runtime_unavailable"
            break


async def run_measurement(runs: int, output: Path, stages: StageTimings) -> dict[str, Any]:
    records: dict[str, Any] = {"workloads": {}, "gate_failures": ["measurement incomplete"]}
    recorder = Recorder(output, records, stages)
    periodic = asyncio.create_task(recorder.periodic())
    try:
        # Timeout cancellation goes through each scan's owned cleanup and case
        # close. It is not a reason to abandon a worker at the 35 minute mark.
        async with asyncio.timeout(MEASUREMENT_BUDGET_SECONDS):
            await measure(runs, records, recorder)
    except Exception as exc:
        records["measurement_error"] = type(exc).__name__
    finally:
        periodic.cancel()
        result = await asyncio.gather(periodic, return_exceptions=True)
        if result and isinstance(result[0], Exception):
            records["checkpoint_error"] = type(result[0]).__name__
            records["measurement_error"] = "checkpoint_failed"
        records["gate_failures"] = gate_failures(records)
        if not records["workloads"]:
            records["gate_failures"].append("no workloads")
        records["qualified"] = False  # S measurements never imply package/host qualification.
        records["component_gates_passed"] = not records["gate_failures"]
        if records["component_gates_passed"]:
            records["loaded_p95_seconds"] = max(
                c["successful_seconds"]["p95"]
                for c in records["workloads"].values()
                if c["kind"] == "loaded"
            )
        await recorder.save()
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.runs < 100:
        parser.error("qualification measurements require at least 100 runs")
    stages = StageTimings()
    with ExitStack() as stack:
        stages.install(stack)
        result = asyncio.run(run_measurement(args.runs, args.output, stages))
    if result["gate_failures"]:
        raise SystemExit("Component latency gates failed: " + "; ".join(result["gate_failures"]))


if __name__ == "__main__":
    main()
