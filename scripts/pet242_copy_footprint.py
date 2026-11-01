"""Three-copy memory, cold-start and concurrency measurement for PET-242's proof gate.

Each scenario runs in a fresh subprocess, because the model holder and the peak
working-set high-water mark both last for the life of a process. Exits non-zero
only for a cold-start or memory failure. Concurrency errors are values for the
operator to accept, and the numbers are always emitted.

Run from a venv holding ``petasos[all]`` with the model cached, with an empty
``HERMES_HOME``.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
import time
from typing import Any

from petasos.config import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.scanners import build_scanners
from petasos.session.ingest import HEAD_CHARS

_COPIES = ("root", "gibson", "ops")
_DISABLED = ("llm_guard", "llama_firewall")
_POLL_SECONDS = 0.5
_COLD_START_DEADLINE = 600.0
# A hung synchronous load never returns to the deadline check in _until_clean, so
# the parent bounds each scenario as well.
_SCENARIO_TIMEOUT = 1800.0
_CALLS_PER_COPY = 8
_NATURAL = (
    "The quarterly report covers revenue, staffing and the migration schedule. "
    "Please review the attached notes and list anything that needs a decision. "
)
_FULL_WINDOW = 8192


def _peak_working_set_mib() -> float | None:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class _Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = _Counters()
    counters.cb = ctypes.sizeof(_Counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_Counters),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    if not psapi.GetProcessMemoryInfo(
        kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    ):
        return None
    return float(counters.PeakWorkingSetSize) / 2**20


def _natural_text(chars: int) -> str:
    return (_NATURAL * (chars // len(_NATURAL) + 1))[:chars]


def _build_pipeline(disabled: tuple[str, ...]) -> Pipeline:
    config = PetasosConfig(disabled_scanners=disabled)
    scanners, statuses = build_scanners(config)
    # A backend that failed construction is not registered, and a minimal-only scan
    # would then pass as a clean ML cold start.
    bad = [s for s in statuses if s.outcome not in ("verified", "disabled")]
    if bad:
        raise RuntimeError(f"scanner not verified: {bad}")
    return Pipeline(scanners=scanners, config=config)


def _unavailable(pipeline: Pipeline) -> str | None:
    for scanner in pipeline._ml_scanners:
        probe = getattr(scanner, "availability", None)
        if probe is None:
            continue
        result = probe()
        if not result[0]:
            return f"{scanner.name}: {result[1]}"
    return None


async def _until_clean(pipeline: Pipeline, row: dict[str, Any]) -> None:
    start = time.monotonic()
    errors: list[str] = []
    while True:
        result = await pipeline.inspect("Please list the files in this folder.")
        seen = dict(pipeline._last_scan_errors)
        for name, error in seen.items():
            line = f"{name}: {error[:80]}"
            if line not in errors:
                errors.append(line)
        if time.monotonic() - start > _COLD_START_DEADLINE:
            raise TimeoutError(f"no clean result in {_COLD_START_DEADLINE}s: {errors}")
        if not seen and result.safe:
            row["seconds"] = round(time.monotonic() - start, 2)
            row["errors_seen"] = errors
            return
        reason = _unavailable(pipeline)
        if reason is not None:
            raise RuntimeError(f"availability turned false: {reason}")
        await asyncio.sleep(_POLL_SECONDS)


def _cold_start_worker(pipeline: Pipeline, row: dict[str, Any], gate: threading.Barrier) -> None:
    gate.wait()
    try:
        asyncio.run(_until_clean(pipeline, row))
    except Exception as exc:
        row["failed"] = f"{type(exc).__name__}: {exc}"


def _concurrency_worker(
    pipeline: Pipeline, payload: str, row: dict[str, Any], gate: threading.Barrier
) -> None:
    """Eight calls behind one per-copy lock, as the plugin's inspect mutex serializes them."""

    async def main() -> None:
        lock = asyncio.Lock()
        gate.wait()
        submitted = time.monotonic()
        totals: list[float] = []
        held: list[float] = []
        errors: list[str] = []

        async def call() -> None:
            async with lock:
                t0 = time.monotonic()
                await pipeline.inspect(payload)
                now = time.monotonic()
                held.append(now - t0)
                totals.append(now - submitted)
                errors.extend(
                    f"{name}: {error[:80]}" for name, error in pipeline._last_scan_errors.items()
                )

        await asyncio.gather(*(call() for _ in range(_CALLS_PER_COPY)))
        row["submit_to_completion_worst_s"] = round(max(totals), 3)
        row["lock_held_scan_worst_s"] = round(max(held), 3)
        row["error_results"] = len(errors)
        row["errors"] = sorted(set(errors))

    asyncio.run(main())


def _run_threads(target: Any, args_per_thread: list[tuple[Any, ...]]) -> None:
    threads = [threading.Thread(target=target, args=args) for args in args_per_thread]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def _cold_start(pipelines: list[Pipeline]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = [{"copy": copy} for copy in _COPIES[: len(pipelines)]]
    gate = threading.Barrier(len(pipelines))
    _run_threads(
        _cold_start_worker, [(p, row, gate) for p, row in zip(pipelines, rows, strict=True)]
    )
    return {"copies": rows, "failed": any("failed" in row for row in rows)}


def _concurrency(pipelines: list[Pipeline], chars: int) -> dict[str, Any]:
    payload = _natural_text(chars)
    rows: list[dict[str, Any]] = [{"copy": copy} for copy in _COPIES]
    gate = threading.Barrier(len(pipelines))
    _run_threads(
        _concurrency_worker,
        [(p, payload, row, gate) for p, row in zip(pipelines, rows, strict=True)],
    )
    return {"chars": chars, "copies": rows}


def _scenario(name: str) -> dict[str, Any]:
    if name == "prompt_guard_alone":
        pipelines = [_build_pipeline((*_DISABLED, "presidio"))]
    elif name == "presidio_alone":
        pipelines = [_build_pipeline((*_DISABLED, "prompt_guard"))]
    else:
        pipelines = [_build_pipeline(_DISABLED) for _ in _COPIES]
    report: dict[str, Any] = {"scenario": name, "cold_start": _cold_start(pipelines)}
    report["peak_working_set_mib_after_load"] = _peak_working_set_mib()
    if name == "presidio_alone":
        report["torch_present"] = "torch" in sys.modules
    if name == "three_copies":
        import torch

        report["torch_threads"] = torch.get_num_threads()
        report["concurrency"] = [
            _concurrency(pipelines, HEAD_CHARS),
            _concurrency(pipelines, _FULL_WINDOW),
        ]
        report["peak_working_set_mib_after_concurrency"] = _peak_working_set_mib()
    return report


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--scenario":
        print(json.dumps(_scenario(sys.argv[2])))
        return 0
    failed = False
    for name in ("prompt_guard_alone", "presidio_alone", "three_copies"):
        try:
            proc = subprocess.run(
                [sys.executable, __file__, "--scenario", name],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=_SCENARIO_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            failed = True
            print(json.dumps({"scenario": name, "timed_out_after_s": _SCENARIO_TIMEOUT}))
            continue
        lines = proc.stdout.strip().splitlines()
        try:
            report = json.loads(lines[-1])
        except (IndexError, ValueError):
            failed = True
            print(
                json.dumps(
                    {"scenario": name, "exit": proc.returncode, "stderr": proc.stderr[-2000:]}
                )
            )
            continue
        print(json.dumps(report, indent=2))
        peak = report["peak_working_set_mib_after_load"]
        if (
            proc.returncode
            or report["cold_start"]["failed"]
            or (sys.platform == "win32" and peak is None)
        ):
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
