"""Runtime ownership tests. Fake jobs test scheduling, not code detection."""

import asyncio
import concurrent.futures
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from petasos.scanners import _semgrep_runtime as rt
from petasos.scanners._semgrep_engine import result_for
from petasos.scanners._semgrep_source import select_sources
from petasos.scanners.semgrep import SemgrepLifecycleOwner, SemgrepScanner
from tests._semgrep_helpers import require


@pytest.fixture
def fake_engine(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr("petasos.scanners.semgrep.supported_platform", lambda: True)
    monkeypatch.setattr("petasos.scanners.semgrep.monitor_available", lambda: True)

    async def execute(runtime: rt.Runtime, job: rt.Job) -> None:
        try:
            if job.selection is None:
                result = rt.error_result("probe_test")
                result = type(result)("semgrep", (), 0)
            else:
                while not job.cancelled.is_set():
                    await asyncio.sleep(0.002)
                result = result_for(job.selection, error="semgrep.cancelled")
        finally:
            with runtime.lock:
                runtime.active.discard(job)
                if job.selection is None:
                    runtime.probe = None
                    runtime.availability_error = None
                job.future.set_result(result)
                runtime._pump()

    monkeypatch.setattr(rt.Runtime, "_execute", execute)
    return {"engine_path": os.path.abspath("synthetic-engine"), "engine_sha256": "a" * 64}


async def ready(scanner: SemgrepScanner) -> None:
    end = time.monotonic() + 8
    while scanner.availability()[1] == "semgrep.probe_pending" and time.monotonic() < end:
        await asyncio.sleep(0.01)
    assert scanner.availability() == (True, None)


async def test_context_is_inert_and_closed_adapter_cannot_reopen(
    fake_engine: dict[str, Any],
) -> None:
    async with SemgrepLifecycleOwner() as owner:
        scanner = SemgrepScanner(owner=owner, **fake_engine)
        await ready(scanner)
        no_code = await scanner.scan("Hello.")
        assert no_code.error is None
        runtime = require(scanner._lease).runtime
    assert not runtime.thread.is_alive()
    assert (await scanner.scan("Hello.")).error == "semgrep.lease_closed"
    with pytest.raises(RuntimeError):
        await owner.__aenter__()


async def test_cancel_is_owned_and_close_does_not_cancel_sibling(
    fake_engine: dict[str, Any],
) -> None:
    async with SemgrepLifecycleOwner() as first, SemgrepLifecycleOwner() as second:
        left = SemgrepScanner(owner=first, **fake_engine)
        right = SemgrepScanner(owner=second, **fake_engine)
        await ready(left)
        scan = asyncio.create_task(left.scan("eval(data)"))
        await asyncio.sleep(0.03)
        result = await left.aclose()
        assert result.status == "closed", result
        assert (await scan).error == "semgrep.cancelled"
        assert not require(right._lease).closed
        assert require(right._lease).runtime.thread.is_alive()
        assert (await right.scan("Hello.")).error is None


async def test_repeated_caller_cancellation_does_not_detach_job(
    fake_engine: dict[str, Any],
) -> None:
    async with SemgrepLifecycleOwner() as owner:
        scanner = SemgrepScanner(owner=owner, **fake_engine)
        await ready(scanner)
        task = asyncio.create_task(scanner.scan("eval(data)"))
        await asyncio.sleep(0.02)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with require(scanner._lease).runtime.lock:
            assert not require(scanner._lease).runtime.active
            assert not require(scanner._lease).tokens


async def test_ten_prepared_results_and_terminal_access_after_close(
    fake_engine: dict[str, Any],
) -> None:
    async with SemgrepLifecycleOwner() as owner:
        scanner = SemgrepScanner(owner=owner, **fake_engine)
        await ready(scanner)
        binding = object()
        tokens = [await scanner.prepare("hello", binding=binding) for _ in range(10)]
        extra = await scanner.prepare("hello", binding=binding)
        assert extra.outcome.error == "semgrep.prepared_capacity"
        assert len(require(scanner._lease).tokens) == 10
        assert tokens[0].consume(object(), "hello") is None
        assert tokens[0].consume(binding, "hello") is not None
        assert tokens[0].consume(binding, "hello") is None
    for token in tokens:
        assert require((await token.discard()).coverage).status == "no_targets"
        assert token._text is None
    assert not require(scanner._lease).runtime.thread.is_alive()


async def test_foreign_thread_constructor_and_foreign_loop_scan(
    fake_engine: dict[str, Any],
) -> None:
    async with SemgrepLifecycleOwner() as owner:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            scanner = pool.submit(SemgrepScanner, owner=owner, **fake_engine).result(timeout=1)
            await ready(scanner)
            result = pool.submit(asyncio.run, scanner.scan("hello")).result(timeout=1)
            assert result.error is None


async def test_shared_owner_three_keys_twelve_jobs_and_queued_cancellation(
    fake_engine: dict[str, Any],
) -> None:
    async with SemgrepLifecycleOwner() as owner:
        scanners = [
            SemgrepScanner(owner=owner, semgrep_scheduling_key=object(), **fake_engine)
            for _ in range(3)
        ]
        await ready(scanners[0])
        selection = await select_sources("eval(data)")
        runtime = require(scanners[0]._lease).runtime
        jobs = [
            runtime.submit(require(scanners[i % 3]._lease), selection, time.monotonic() + 8)
            for i in range(12)
        ]
        extra = runtime.submit(require(scanners[0]._lease), selection, time.monotonic() + 8)
        assert extra.future.result().error == "semgrep.queue_full"
        runtime.cancel(jobs[-1])
        replacement = runtime.submit(require(scanners[2]._lease), selection, time.monotonic() + 8)
        assert not replacement.future.done()
        with runtime.lock:
            assert len(runtime.active) <= 2
            assert len(runtime.active) + sum(map(len, runtime.pending.values())) == 12
        for job in jobs + [replacement]:
            runtime.cancel(job)
        await asyncio.gather(*(rt.await_job(job) for job in jobs + [replacement]))


async def test_queued_deadline_releases_capacity_while_both_workers_are_busy(
    fake_engine: dict[str, Any],
) -> None:
    async with SemgrepLifecycleOwner() as owner:
        scanner = SemgrepScanner(owner=owner, **fake_engine)
        await ready(scanner)
        lease = require(scanner._lease)
        runtime = lease.runtime
        selection = await select_sources("eval(data)")
        active = [runtime.submit(lease, selection, time.monotonic() + 8) for _ in range(2)]
        end = time.monotonic() + 1
        while len(runtime.active) < 2 and time.monotonic() < end:
            await asyncio.sleep(0.005)
        assert len(runtime.active) == 2
        queued = runtime.submit(lease, selection, time.monotonic() + 0.05)
        result = await asyncio.wait_for(rt.await_job(queued), 0.5)
        assert result.error == "semgrep.queue_deadline"
        assert queued.selection is None
        with runtime.lock:
            assert len(runtime.active) == 2
            assert not runtime.pending
        for job in active:
            runtime.cancel(job)
        await asyncio.gather(*(rt.await_job(job) for job in active))


async def test_cpu_cancellation_waits_for_owned_worker() -> None:
    import threading

    from petasos.scanners._semgrep_engine import await_cpu

    cancelled, release, entered = threading.Event(), threading.Event(), threading.Event()

    def work() -> int:
        entered.set()
        assert release.wait(1)
        return 42

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(work)
        task = asyncio.create_task(
            await_cpu(
                worker, time.monotonic() + 8, cancelled, rt.error_result("semgrep.cleanup_failed")
            )
        )
        while not entered.is_set():
            await asyncio.sleep(0.001)
        cancelled.set()
        await asyncio.sleep(0.02)
        assert not task.done()
        release.set()
        result = await asyncio.wait_for(task, 0.5)
        assert result.value is None
        assert result.error == "semgrep.cancelled"
        assert worker.done()


async def test_owner_cleanup_failure_preserves_body_exception(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from petasos.scanners import semgrep

    async def failure(*args: Any, **kwargs: Any) -> rt.SemgrepCloseResult:
        return rt.SemgrepCloseResult("failed", jobs=1, reasons=("cleanup_failed",))

    monkeypatch.setattr(semgrep, "close_leases", failure)
    owner = SemgrepLifecycleOwner()
    with pytest.raises(ValueError, match="body failure") as caught:
        async with owner:
            raise ValueError("body failure")
    assert require(owner.close_result).status == "failed"
    assert "semgrep.cleanup_failed" in caplog.text
    assert caught.value.__notes__
    with pytest.raises(rt.SemgrepCleanupError):
        async with SemgrepLifecycleOwner():
            pass


async def test_thirteenth_lease_and_engine_identity_conflict(
    fake_engine: dict[str, Any],
) -> None:
    async with SemgrepLifecycleOwner() as owner:
        scanners = [SemgrepScanner(owner=owner, **fake_engine) for _ in range(12)]
        await ready(scanners[0])
        extra = SemgrepScanner(owner=owner, **fake_engine)
        assert extra.availability() == (False, "semgrep.lease_exhausted")
        assert extra._lease is None
        conflict = SemgrepScanner(owner=owner, **(fake_engine | {"engine_sha256": "b" * 64}))
        assert conflict.availability() == (False, "semgrep.engine_identity_conflict")
        assert conflict._lease is None


def test_stale_roots_are_removed_only_with_dead_verified_owners(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    psutil = pytest.importorskip("psutil")
    from petasos.scanners._semgrep_roots import recover_roots

    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: pid == 123)
    for name, marker in (
        ("psg-dead0000", {"schema": 1, "pid": 124, "born": 1, "children": []}),
        ("psg-live0000", {"schema": 1, "pid": 123, "born": 1, "children": []}),
        (
            "psg-child000",
            {"schema": 1, "pid": 124, "born": 1, "children": [{"pid": 123, "born": 1}]},
        ),
        ("psg-invalid0", {"schema": 1, "pid": 124, "born": 1, "children": ["bad"]}),
    ):
        root = tmp_path / name
        root.mkdir()
        (root / "petasos-owner.json").write_text(json.dumps(marker), encoding="utf-8")
    unknown = tmp_path / "psg-unknown0"
    unknown.mkdir()
    assert recover_roots() == 1
    assert not (tmp_path / "psg-dead0000").exists()
    assert all(
        (tmp_path / name).exists()
        for name in ("psg-live0000", "psg-child000", "psg-invalid0", "psg-unknown0")
    )


async def test_transient_root_lock_is_retried_within_cleanup_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "owned"
    root.mkdir()
    (root / "candidate.source").write_text("synthetic", encoding="utf-8")
    import shutil

    original = shutil.rmtree
    attempts = 0

    def locked_once(path: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("synthetic transient sharing violation")
        original(path)

    monkeypatch.setattr(shutil, "rmtree", locked_once)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        await rt.remove_root(
            root, executor, time.monotonic() + 0.5, rt.error_result("semgrep.cleanup_failed")
        )
    assert attempts == 2
    assert not root.exists()


async def test_projection_only_starts_in_two_admitted_active_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    monkeypatch.setattr("petasos.scanners.semgrep.supported_platform", lambda: True)
    monkeypatch.setattr("petasos.scanners.semgrep.monitor_available", lambda: True)
    monkeypatch.setattr(
        rt.Runtime, "_enqueue_probe", lambda runtime: setattr(runtime, "availability_error", None)
    )
    monkeypatch.setattr(rt.Runtime, "_verify_identity", lambda runtime: None)
    release = threading.Event()
    original = select_sources
    entered = 0

    async def held_projection(*args: Any, **kwargs: Any) -> Any:
        nonlocal entered
        entered += 1
        while not release.is_set():
            await asyncio.sleep(0.001)
        return await original(*args, **kwargs)

    monkeypatch.setattr(rt, "select_sources", held_projection)
    async with SemgrepLifecycleOwner() as owner:
        scanners = [
            SemgrepScanner(
                owner=owner, engine_path=os.path.abspath("synthetic"), engine_sha256="a" * 64
            )
            for _ in range(3)
        ]
        tasks = [asyncio.create_task(scanners[i % 3].scan("eval(data)")) for i in range(12)]
        runtime = require(scanners[0]._lease).runtime
        try:
            until = time.monotonic() + 1
            while entered < 2 and time.monotonic() < until:
                await asyncio.sleep(0.001)
            assert entered == 2
            await asyncio.sleep(0.02)
            assert entered == 2
            with runtime.lock:
                assert len(runtime.active) == 2
                assert sum(map(len, runtime.pending.values())) == 10
                assert all(
                    job.selection is not None and not job.selection.targets
                    for queue in runtime.pending.values()
                    for job in queue
                )
            extra = await scanners[0].scan("eval(data)")
            assert extra.error == "semgrep.queue_full"
            for benign in (
                '{"title":"hello world","items":[1,2,3]}',
                '{"title":"hello \\u0077orld","items":[]}',
                '"hello world"',
            ):
                result = await asyncio.wait_for(scanners[0].scan(benign), 0.5)
                assert result.error is None
                assert require(result.coverage).status == "no_targets"
            escaped = await scanners[0].scan('"\\u0065\\u0076\\u0061\\u006c\\u0028x)"')
            assert escaped.error == "semgrep.queue_full"  # Code still needs admission.
        finally:
            with runtime.lock:
                for job in [
                    *runtime.active,
                    *(job for queue in runtime.pending.values() for job in queue),
                ]:
                    runtime.cancel(job)
            release.set()
            await asyncio.gather(*tasks)


@pytest.mark.skipif(not os.environ.get("SEMGREP_ENGINE_PATH"), reason="isolated engine required")
async def test_real_owned_probe_scan_and_clean_close() -> None:
    engine = os.environ["SEMGREP_ENGINE_PATH"]
    with open(engine, "rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    async with SemgrepLifecycleOwner() as owner:
        scanner = SemgrepScanner(owner=owner, engine_path=engine, engine_sha256=digest)
        await ready(scanner)
        result = await scanner.scan("eval(data)")
        assert result.error is None
        assert result.findings
    assert require(owner.close_result).status == "closed"
    assert not require(scanner._lease).runtime.thread.is_alive()


def test_process_close_deadline_terminal_tokens_and_permanent_seal() -> None:
    script = Path(__file__).parent / "fixtures/semgrep/close_owner.py"
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr


async def test_cancelled_native_worker_cleanup_failure_is_not_discarded() -> None:
    import threading

    from petasos.scanners._semgrep_engine import await_cpu
    from petasos.scanners._semgrep_process import CleanupFailure

    cancelled = threading.Event()
    cancelled.set()
    failure = CleanupFailure(object())  # type: ignore[arg-type]
    worker: concurrent.futures.Future[Any] = concurrent.futures.Future()
    worker.set_exception(failure)
    with pytest.raises(CleanupFailure) as caught:
        await await_cpu(
            worker, time.monotonic() + 8, cancelled, rt.error_result("semgrep.cleanup_failed")
        )
    assert caught.value is failure


async def test_stuck_native_worker_retains_future_after_cancellation() -> None:
    import threading

    from petasos.scanners import _semgrep_engine as engine

    cancelled, release = threading.Event(), threading.Event()
    cancelled.set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(release.wait)
        try:
            with pytest.raises(engine.CpuCleanupFailure) as caught:
                await engine.await_cpu(
                    worker,
                    time.monotonic() + 8,
                    cancelled,
                    rt.error_result("semgrep.cleanup_failed"),
                )
            assert caught.value.future is worker
            assert not worker.done()
        finally:
            release.set()
            await asyncio.wrap_future(worker)
