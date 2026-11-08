"""Real-engine replacement cleanup under CPU load. Run by hand; not a CI test.

Counts clean, cleanup_failed, recovered and expired iterations. A recovered
iteration is also counted as cleanup_failed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import subprocess
import sys
import tempfile
import time
from typing import Any


def _parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, required=True)
    parser.add_argument("--load", type=int, required=True)
    args = parser.parse_args()
    if args.iterations < 1 or args.load < 1:
        parser.error("iterations and load must be positive")
    return args


def _spawn_load(count: int) -> list[subprocess.Popen[bytes]]:
    code = "while True:\n    pass\n"
    return [subprocess.Popen([sys.executable, "-c", code]) for _ in range(count)]


def _stop_load(procs: list[subprocess.Popen[bytes]]) -> None:
    for proc in procs:
        proc.terminate()
    for proc in procs:
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def _digest(path: str) -> str:
    pinned = os.environ.get("SEMGREP_ENGINE_SHA256")
    if pinned:
        return pinned
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _labels(lines: list[str], failed: bool, error: str | None) -> set[str]:
    labels: set[str] = set()
    if any("outcome=expired" in line for line in lines):
        labels.add("expired")
    if any("outcome=recovered" in line for line in lines):
        labels.add("recovered")
    if (
        failed
        or error == "semgrep.cleanup_failed"
        or any(
            line.startswith("kind=native") or line.startswith("kind=root_removal")
            for line in lines
        )
    ):
        labels.add("cleanup_failed")
    if not labels:
        labels.add("clean")
    return labels


async def _run(iterations: int) -> tuple[dict[str, int], str, tuple[str, ...]]:
    from petasos.scanners._semgrep_runtime import SemgrepCleanupError
    from petasos.scanners.semgrep import SemgrepLifecycleOwner

    counts = {"clean": 0, "cleanup_failed": 0, "recovered": 0, "expired": 0}
    owner = SemgrepLifecycleOwner()
    try:
        async with owner:
            await _iterate(owner, iterations, counts)
    except SemgrepCleanupError as exc:
        # A failure still open at close is a result to record, not a crash: the
        # owner reports it after every iteration has been counted.
        return counts, exc.result.status, exc.result.diagnostics
    return counts, "closed", ()


async def _iterate(owner: Any, iterations: int, counts: dict[str, int]) -> None:
    from petasos.scanners.semgrep import SemgrepScanner
    from scripts.semgrep_benchmark_protocol import fixtures

    engine = os.environ["SEMGREP_ENGINE_PATH"]
    digest = _digest(engine)
    _, sources = fixtures()
    text = sources["single_16k"]["text"]
    scanner = SemgrepScanner(owner=owner, engine_path=engine, engine_sha256=digest)
    deadline = time.monotonic() + 30
    while scanner.availability()[1] == "semgrep.probe_pending" and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    if not scanner.availability()[0]:
        raise SystemExit(f"probe unavailable: {scanner.availability()[1]}")
    lease = scanner._lease
    assert lease is not None
    runtime = lease.runtime
    for _ in range(iterations):
        with runtime.lock:
            before = list(runtime.cleanup_diagnostics)
            failed_before = runtime.failed
        active = [asyncio.create_task(scanner.scan(text)) for _ in range(2)]
        until = time.monotonic() + 8
        while time.monotonic() < until:
            with runtime.lock:
                if len(runtime.active) >= 2:
                    break
            await asyncio.sleep(0.01)
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)
        error: str | None = None
        try:
            result = await asyncio.wait_for(scanner.scan(text), 45)
            error = result.error
        except TimeoutError:
            error = "semgrep.cleanup_failed"
        with runtime.lock:
            fresh = [line for line in runtime.cleanup_diagnostics if line not in before]
            failed = runtime.failed or failed_before
        for label in _labels(fresh, failed, error):
            counts[label] += 1


def main() -> None:
    args = _parse()
    if "HERMES_HOME" not in os.environ:
        os.environ["HERMES_HOME"] = tempfile.mkdtemp(prefix="pet255-hermes-")
    procs = _spawn_load(args.load)
    try:
        counts, close_status, close_diagnostics = asyncio.run(_run(args.iterations))
    finally:
        _stop_load(procs)
    print(
        "clean={clean} cleanup_failed={cleanup_failed} recovered={recovered} "
        "expired={expired} iterations={iterations}".format(iterations=args.iterations, **counts)
    )
    print(f"close={close_status}")
    for line in close_diagnostics:
        print(f"close_diagnostic {line}")


if __name__ == "__main__":
    main()
