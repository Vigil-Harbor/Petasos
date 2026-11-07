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
import statistics
import subprocess
import threading
import time
from collections import defaultdict
from contextlib import ExitStack
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
from unittest.mock import patch

from petasos.scanners._semgrep_source import preflight
from petasos.scanners.semgrep import SemgrepLifecycleOwner, SemgrepScanner


def summary(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {
        "runs": len(values),
        "mean": statistics.mean(values),
        "p95": ordered[int((len(ordered) - 1) * 0.95)],
        "p99": ordered[int((len(ordered) - 1) * 0.99)],
        "max": max(values),
    }


class StageTimings:
    """Benchmark-only wrappers; store durations, never arguments/source text."""

    def __init__(self) -> None:
        self.values: dict[str, list[float]] = defaultdict(list)
        self.lock = threading.Lock()

    def wrap(self, name: str, function: Callable[..., Any]) -> Callable[..., Any]:
        def record(start: float) -> None:
            with self.lock:
                self.values[name].append(time.monotonic() - start)

        if inspect.iscoroutinefunction(function):

            @wraps(function)
            async def asynchronous(*args: Any, **kwargs: Any) -> Any:
                started = time.monotonic()
                try:
                    return await function(*args, **kwargs)
                finally:
                    record(started)

            return asynchronous

        @wraps(function)
        def synchronous(*args: Any, **kwargs: Any) -> Any:
            started = time.monotonic()
            try:
                return function(*args, **kwargs)
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


async def measure(runs: int, records: dict[str, Any]) -> dict[str, Any]:
    import psutil

    engine = os.environ["SEMGREP_ENGINE_PATH"]
    with open(engine, "rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    rules = Path(__file__).resolve().parents[1] / "petasos/scanners/semgrep_rules/rules.json"
    records.update(
        {
            "schema_version": 1,
            "implementation": revision(),
            "engine_version": "1.183.0",
            "engine_sha256": digest,
            "rules_sha256": hashlib.sha256(rules.read_bytes()).hexdigest(),
            "hardware": {
                "architecture": platform.machine(),
                "os": platform.platform(),
                "cpu": platform.processor(),
                "logical_cores": os.cpu_count(),
                "ram_bytes": psutil.virtual_memory().total,
            },
            "workloads": {},
        }
    )

    def source(size: int) -> str:
        tail = "\neval(payload)\n"
        lines = ["import json\n"]
        used = len(lines[0])
        index = 0
        while True:
            line = f"value_{index:04d} = json.loads(payload).get('value', 0)\n"
            if used + len(line) + len(tail) + 2 > size:
                break
            lines.append(line)
            used += len(line)
            index += 1
        return "".join(lines) + "#" + "p" * (size - used - len(tail) - 1) + tail

    cold_started = time.monotonic()
    async with (
        SemgrepLifecycleOwner() as owner,
        SemgrepLifecycleOwner() as second,
        SemgrepLifecycleOwner() as third,
    ):
        scanners = [
            SemgrepScanner(
                owner=owner,
                engine_path=engine,
                engine_sha256=digest,
                semgrep_scheduling_key=object(),
            )
            for _ in range(3)
        ]
        until = time.monotonic() + 8
        while (
            scanners[0].availability()[1] == "semgrep.probe_pending" and time.monotonic() < until
        ):
            await asyncio.sleep(0.01)
        if not scanners[0].availability()[0]:
            raise RuntimeError(scanners[0].availability()[1])
        records["cold_probe_seconds"] = time.monotonic() - cold_started

        async def scan(
            index: int, text: str, segments: tuple[tuple[int, int], ...] | None
        ) -> float:
            started = time.monotonic()
            scanner = scanners[index]
            token = await scanner.prepare(text, binding=scanner, segments=segments)
            try:
                result = token.consume(scanner, text)
                if result is None or result.error or not result.findings:
                    raise RuntimeError(
                        "benchmark scan failed: "
                        + (result.error or "missing finding" if result else "invalid token")
                    )
            finally:
                await token.discard()
            return time.monotonic() - started

        single = source(16384)
        part = source(8192)
        maximum = "\n".join([part] * 16)
        segments = tuple((i * 8193, i * 8193 + 8192) for i in range(16))
        for name, text, spans in (
            ("single_16k", single, None),
            ("sixteen_128k", maximum, segments),
        ):
            await scan(0, text, spans)
            values = [await scan(0, text, spans) for _ in range(runs)]
            records["workloads"][name] = summary(values)
            print(name, json.dumps(records["workloads"][name]), flush=True)
        for topology in ("shared_owner", "three_owners"):
            if topology == "three_owners":
                scanners = [
                    SemgrepScanner(
                        owner=scope,
                        engine_path=engine,
                        engine_sha256=digest,
                        semgrep_scheduling_key=object(),
                    )
                    for scope in (owner, second, third)
                ]
            for distribution in ((3, 3, 2), (4, 2, 2), (8, 0, 0)):
                values = []
                for _ in range(max(2, runs // 10)):
                    values.extend(
                        await asyncio.gather(
                            *(
                                scan(index, single, None)
                                for index, count in enumerate(distribution)
                                for _ in range(count)
                            )
                        )
                    )
                name = "eight_wide_" + topology + "_" + "_".join(map(str, distribution))
                records["workloads"][name] = summary(values)
                print(name, json.dumps(records["workloads"][name]), flush=True)
        values = []
        lease = scanners[0]._lease
        assert lease is not None
        for _ in range(max(2, runs // 10)):
            cancelled = [asyncio.create_task(scanners[0].scan(single)) for _ in range(2)]
            until = time.monotonic() + 2
            while time.monotonic() < until:
                with lease.runtime.lock:
                    if len(lease.runtime.active) == 2:
                        break
                await asyncio.sleep(0.001)
            else:
                raise RuntimeError("replacement workload did not reach two active jobs")
            for task in cancelled:
                task.cancel()
            values.extend(await asyncio.gather(*(scan(0, single, None) for _ in range(8))))
            outcomes = await asyncio.gather(*cancelled, return_exceptions=True)
            if not all(isinstance(outcome, asyncio.CancelledError) for outcome in outcomes):
                raise RuntimeError("replacement workload missed active cancellation")
        records["workloads"]["eight_replacements"] = summary(values)
        print("eight_replacements", json.dumps(summary(values)), flush=True)
        values = []
        text = "benign words " * 76923
        for _ in range(runs):
            started = time.monotonic()
            await preflight(text)
            values.append(time.monotonic() - started)
        records["workloads"]["preflight_1m"] = summary(values)
    records["close"] = owner.close_result.status if owner.close_result else "missing"
    failures = []
    for name in ("single_16k", "sixteen_128k"):
        for metric, limit in (("mean", 1.0), ("p95", 1.2), ("p99", 1.4)):
            if records["workloads"][name][metric] > limit:
                failures.append(f"{name}.{metric} > {limit}s")
    for name, values in records["workloads"].items():
        loaded_limit = (
            5
            if name.startswith("eight_wide_")
            else 7.5
            if name == "eight_replacements"
            else 0.05
            if name == "preflight_1m"
            else None
        )
        if loaded_limit is not None and values["p95"] > loaded_limit:
            failures.append(f"{name}.p95 > {loaded_limit}s")
    if records["close"] != "closed":
        failures.append("owned close failed")
    records["gate_failures"] = failures
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.runs < 100:
        parser.error("qualification measurements require at least 100 runs")
    stages = StageTimings()
    result: dict[str, Any] = {}
    with ExitStack() as stack:
        stages.install(stack)
        try:
            asyncio.run(measure(args.runs, result))
        except Exception as exc:
            # Preserve partial workloads and stage timings on functional failure
            # as well as on a missed latency threshold. Never certify this run.
            result["measurement_error"] = type(exc).__name__ + ": " + str(exc)
            result["gate_failures"] = ["measurement did not complete"]
    result["stage_durations_seconds"] = {
        name: summary(values) for name, values in stages.values.items()
    }
    result["workload_description"] = (
        "dense Python JSON transforms and one eval; equal-size raw parts"
    )
    if result.get("implementation", {}).get("tracked_dirty", True):
        result["gate_failures"].append("tracked working tree is dirty")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if result["gate_failures"]:
        raise SystemExit("Component latency gates failed: " + "; ".join(result["gate_failures"]))


if __name__ == "__main__":
    main()
