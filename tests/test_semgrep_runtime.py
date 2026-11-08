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


async def _bounded_result(task: asyncio.Task[Any]) -> Any:
    # wait_for cancels its target and can itself hang on cancellation-resistant
    # ownership code. Inspect completion without cancelling the target instead.
    done, _ = await asyncio.wait({task}, timeout=1)
    assert task in done, "controlled-clock regression did not terminate"
    return task.result()


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
    empty_old = tmp_path / "psg-emptyold"
    empty_new = tmp_path / "psg-emptynew"
    nonempty = tmp_path / "psg-nonempty"
    future = tmp_path / "psg-future00"
    for path in (empty_old, empty_new, nonempty, future):
        path.mkdir()
    (nonempty / "left.txt").write_text("stay", encoding="utf-8")
    now = time.time()
    os.utime(empty_old, (now - 660, now - 660))
    os.utime(empty_new, (now - 300, now - 300))
    os.utime(nonempty, (now - 660, now - 660))
    os.utime(future, (now + 600, now + 600))
    # Regression for PET-255: empty marker-less roots older than ten minutes are removed.
    assert recover_roots() == 2
    assert not (tmp_path / "psg-dead0000").exists()
    assert not empty_old.exists()
    assert all(
        path.exists()
        for path in (
            tmp_path / "psg-live0000",
            tmp_path / "psg-child000",
            tmp_path / "psg-invalid0",
            unknown,
            empty_new,
            nonempty,
            future,
        )
    )
    assert recover_roots() == 0
    os.utime(empty_new, (now - 660, now - 660))
    assert recover_roots() == 1
    assert not empty_new.exists()
    assert nonempty.exists()
    assert (nonempty / "left.txt").is_file()


async def test_transient_root_lock_is_retried_within_cleanup_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "owned"
    root.mkdir()
    (root / "candidate.source").write_text("synthetic", encoding="utf-8")
    from petasos.scanners import _semgrep_roots as roots

    original = roots.remove_owned_root
    attempts = 0

    def locked_once(path: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("synthetic transient sharing violation")
        original(path)

    monkeypatch.setattr(roots, "remove_owned_root", locked_once)
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


async def test_native_cleanup_uses_worker_deadline_without_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    from types import SimpleNamespace

    from petasos.scanners import _semgrep_engine as engine

    clock = [0.0]
    monkeypatch.setattr(engine, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    cancelled = threading.Event()
    cancelled.set()
    worker: concurrent.futures.Future[int] = concurrent.futures.Future()
    reported: list[float | None] = [None]
    task = asyncio.create_task(
        engine.await_cpu(
            worker,
            8,
            cancelled,
            rt.error_result("semgrep.cleanup_failed"),
            cleanup_deadline=lambda: reported[0],
        )
    )
    await asyncio.sleep(0.02)
    # Constructor finishes after cancellation. Native cleanup starts at .5,
    # has exactly two seconds, and reports the same absolute end to both sides.
    reported[0] = 2.5
    clock[0] = 2.1
    await asyncio.sleep(0.02)
    assert not task.done()  # The supervisor's independent 2.0 deadline is gone.
    worker.set_result(42)
    result = await _bounded_result(task)
    assert result.error == "semgrep.cancelled"


async def test_native_cleanup_waits_for_worker_verdict_until_total_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression for PET-255: a reported native end does not cut the wait short of total_end.
    import threading
    from types import SimpleNamespace

    from petasos.scanners import _semgrep_engine as engine

    clock = [0.0]
    monkeypatch.setattr(engine, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    cancelled = threading.Event()
    cancelled.set()
    worker: concurrent.futures.Future[int] = concurrent.futures.Future()
    task = asyncio.create_task(
        engine.await_cpu(
            worker,
            8,
            cancelled,
            rt.error_result("semgrep.cleanup_failed"),
            cleanup_deadline=lambda: 1.0,
        )
    )
    await asyncio.sleep(0.02)
    clock[0] = 1.01
    await asyncio.sleep(0.02)
    assert not task.done()
    worker.set_result(7)
    result = await _bounded_result(task)
    assert result.error == "semgrep.cancelled"

    clock[0] = 0.0
    unfinished: concurrent.futures.Future[int] = concurrent.futures.Future()
    stalled = asyncio.create_task(
        engine.await_cpu(
            unfinished,
            8,
            cancelled,
            rt.error_result("semgrep.cleanup_failed"),
            cleanup_deadline=lambda: 1.0,
        )
    )
    await asyncio.sleep(0.02)
    clock[0] = 4.0
    try:
        with pytest.raises(engine.CpuCleanupFailure) as caught:
            await _bounded_result(stalled)
        assert caught.value.future is unfinished
    finally:
        unfinished.set_result(42)


@pytest.mark.parametrize("reported,end", [(None, 2.0), (3.99, 4.0), (9.0, 4.0)])
async def test_scan_cancellation_observes_constructor_and_cleanup_caps(
    monkeypatch: pytest.MonkeyPatch, reported: float | None, end: float
) -> None:
    """Caller/glue test, not runtime E2E; report is constant, not late-published."""
    from types import SimpleNamespace

    from petasos.scanners import _semgrep_engine as engine

    clock = [0.0]
    monkeypatch.setattr(engine, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    job = rt.Job(None, object(), None, 8, 8)
    job.lease = SimpleNamespace(  # type: ignore[assignment]
        runtime=SimpleNamespace(cancel=lambda item: item.cancelled.set())
    )
    worker: concurrent.futures.Future[int] = concurrent.futures.Future()
    caller = asyncio.create_task(rt.await_job(job))
    await asyncio.sleep(0)
    caller.cancel()
    await asyncio.sleep(0)
    assert job.cancelled.is_set()

    async def finish_job() -> None:
        try:
            await engine.await_cpu(
                worker,
                job.deadline,
                job.cancelled,
                rt.error_result("semgrep.cleanup_failed"),
                cleanup_deadline=lambda: reported,
            )
        except engine.CpuCleanupFailure as exc:
            job.cpu_failure = exc
            job.future.set_result(exc.outcome)

    producer = asyncio.create_task(finish_job())
    await asyncio.sleep(0.02)
    clock[0] = end - 0.01
    await asyncio.sleep(0.02)
    assert not caller.done()
    clock[0] = end
    try:
        await _bounded_result(producer)
        with pytest.raises(asyncio.CancelledError):
            await _bounded_result(caller)
        assert require(job.cpu_failure).future is worker
        assert not worker.done()  # Terminal error does not release native ownership.
        assert clock[0] <= 4
    finally:
        worker.set_result(42)
        if not job.future.done():
            job.future.set_result(rt.error_result("semgrep.cleanup_failed"))


async def test_late_timeout_observation_cannot_move_request_cleanup_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    from types import SimpleNamespace

    from petasos.scanners import _semgrep_engine as engine

    clock = [8.5]
    monkeypatch.setattr(engine, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    worker: concurrent.futures.Future[int] = concurrent.futures.Future()
    task = asyncio.create_task(
        engine.await_cpu(
            worker,
            8,
            threading.Event(),
            rt.error_result("semgrep.cleanup_failed"),
            cleanup_deadline=lambda: 20,
        )
    )
    await asyncio.sleep(0.02)
    clock[0] = 11.99
    await asyncio.sleep(0.02)
    assert not task.done()
    clock[0] = 12
    try:
        with pytest.raises(engine.CpuCleanupFailure):
            await _bounded_result(task)
    finally:
        worker.set_result(42)


async def test_repeated_close_never_schedules_onto_a_closed_loop(
    fake_engine: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    async with SemgrepLifecycleOwner() as owner:
        scanner = SemgrepScanner(owner=owner, **fake_engine)
        await ready(scanner)
        lease = require(scanner._lease)
        runtime = lease.runtime
    assert runtime.loop.is_closed()
    # A second close racing teardown: the manager thread still looks alive,
    # but its loop has already closed.
    real = runtime.thread
    first = iter([True])
    stub = SimpleNamespace(is_alive=lambda: next(first, real.is_alive()), join=real.join)
    monkeypatch.setattr(runtime, "thread", stub)
    result = await rt.close_leases({lease}, time.monotonic() + 1)
    assert result.status == "closed", result


def _finding() -> Any:
    from petasos._types import ScanFinding, ScanResult, Severity

    return ScanResult(
        "semgrep",
        (
            ScanFinding(
                rule_id="petasos.semgrep.python.dynamic_code",
                finding_type="code",
                severity=Severity.HIGH,
                confidence=1.0,
                message="synthetic",
                scanner_name="semgrep",
            ),
        ),
        0,
    )


class _RuntimeHandle:
    """One runtime whose probe and engine calls stay inside the test."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.monkeypatch = monkeypatch
        self.tmp_path = tmp_path
        self.enqueued: list[str | None] = []
        self.runtime: rt.Runtime | None = None
        self.lease: rt.Lease | None = None
        import tempfile

        # Windows refuses a source root whose path is longer than 80 bytes.
        self.short = Path(tempfile.mkdtemp(prefix="p255"))

    def start(self, scan: Any) -> rt.Runtime:
        import tempfile

        self.monkeypatch.setattr(rt, "_RECOVERIES", 0)
        engine = self.tmp_path / "engine"
        engine.write_bytes(b"engine")
        settings = rt.Settings(str(engine), "a" * 64, timeout=30)
        real_enqueue = rt.Runtime._enqueue_probe
        enqueued = self.enqueued

        def enqueue(runtime: rt.Runtime) -> None:
            if not enqueued:
                enqueued.append("boot")
                runtime.availability_error = None
                return
            enqueued.append(runtime.availability_error)
            real_enqueue(runtime)

        real_execute = rt.Runtime._execute

        async def execute(runtime: rt.Runtime, job: rt.Job) -> None:
            if job.lease is None:
                with runtime.lock:
                    runtime.active.discard(job)
                    if runtime.probe is job:
                        runtime.probe = None
                    runtime.availability_error = None
                    if not job.future.done():
                        job.future.set_result(_finding())
                    runtime._pump()
                return
            await real_execute(runtime, job)

        self.monkeypatch.setattr(rt.Runtime, "_enqueue_probe", enqueue)
        self.monkeypatch.setattr(rt.Runtime, "_execute", execute)
        self.monkeypatch.setattr(rt.Runtime, "_verify_identity", lambda runtime: None)
        self.monkeypatch.setattr(rt, "scan_selected", scan)
        self.monkeypatch.setattr(tempfile, "gettempdir", lambda: str(self.short))
        runtime = rt.Runtime(settings)
        self.runtime = runtime
        lease = runtime.register(settings, object())
        assert isinstance(lease, rt.Lease)
        self.lease = lease
        return runtime

    def submit(self) -> rt.Job:
        from petasos.scanners._semgrep_source import Selection

        assert self.runtime is not None and self.lease is not None
        return self.runtime.submit(self.lease, Selection(), time.monotonic() + 30)

    def stop(self) -> None:
        import shutil

        runtime = self.runtime
        try:
            if runtime is None or not runtime.thread.is_alive():
                return
            if runtime.loop.is_closed():
                runtime.thread.join(1)
                return

            def halt() -> None:
                task = runtime.recovery
                if task is not None and not task.done():
                    task.cancel()
                runtime.stopping = True
                runtime.failed = False
                runtime.active.clear()
                runtime.retained.clear()
                runtime.pending.clear()
                runtime.turns.clear()
                runtime.loop.stop()

            runtime.loop.call_soon_threadsafe(halt)
            runtime.thread.join(5)
        finally:
            shutil.rmtree(self.short, ignore_errors=True)


async def _wait_for(predicate: Any, timeout: float = 3) -> None:
    # perf_counter, not monotonic: recovery tests replace the runtime clock.
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out")


def _jumping_clock(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    """Replace only the runtime module's clock. A frozen jump must not stall tests."""
    import time as real_time

    anchor = real_time.monotonic()
    jump = {"on": False}

    class Clock:
        def monotonic(self) -> float:
            return anchor + 1000 if jump["on"] else real_time.monotonic()

        def __getattr__(self, name: str) -> Any:
            return getattr(real_time, name)

    monkeypatch.setattr(rt, "time", Clock())
    return jump


async def _job_result(job: rt.Job, timeout: float = 3) -> Any:
    return await asyncio.wait_for(asyncio.wrap_future(job.future), timeout)


class _CleanChild:
    def __init__(self, *, delay: float = 0.0, fail_after_close: bool = False) -> None:
        self.delay = delay
        self.fail_after_close = fail_after_close
        self.born = time.monotonic()
        self.closes = 0
        self.cleaned_calls = 0

    def cleaned(self) -> bool:
        self.cleaned_calls += 1
        if self.closes and self.fail_after_close:
            raise OSError("synthetic closed handle")
        return time.monotonic() - self.born >= self.delay

    def close(self) -> None:
        self.closes += 1


async def test_worker_finishing_just_after_reported_end_is_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression for PET-255: success at E + 0.05 is not CpuCleanupFailure.
    import threading
    from types import SimpleNamespace

    from petasos.scanners import _semgrep_engine as engine

    clock = [0.0]
    monkeypatch.setattr(engine, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    cancelled = threading.Event()
    cancelled.set()
    worker: concurrent.futures.Future[int] = concurrent.futures.Future()
    task = asyncio.create_task(
        engine.await_cpu(
            worker,
            8,
            cancelled,
            rt.error_result("semgrep.cleanup_failed"),
            cleanup_deadline=lambda: 1.0,
        )
    )
    await asyncio.sleep(0.02)
    clock[0] = 1.05
    await asyncio.sleep(0.02)
    assert not task.done()
    worker.set_result(1)
    result = await _bounded_result(task)
    assert result.error == "semgrep.cancelled"


def test_removal_deadline_keeps_a_minimum_attempt() -> None:
    # Regression for PET-255: removal has its own budget, floored at 0.25s.
    runtime = rt.Runtime(rt.Settings("engine", "a" * 64))
    try:
        job = rt.Job(None, object(), None, 200.0, 8.0)
        assert runtime._removal_deadline(job, 100.0) == 102.0
        job.cancelled_at = 100.0
        assert runtime._removal_deadline(job, 100.0) == 102.0
        job.cancelled_at = 90.0
        assert runtime._removal_deadline(job, 100.0) == 100.25
        job.cancelled_at = None
        job.deadline = 99.0
        assert runtime._removal_deadline(job, 100.0) == 102.0
        job.deadline = 90.0
        assert runtime._removal_deadline(job, 100.0) == 100.25
        job.deadline = 200.0
        runtime.stopping = True
        runtime.close_started = 100.0
        assert runtime._removal_deadline(job, 100.0) == 102.0
        runtime.close_started = 90.0
        assert runtime._removal_deadline(job, 100.0) == 100.25
    finally:
        runtime.loop.call_soon_threadsafe(runtime.loop.stop)
        runtime.thread.join(5)


async def test_post_exit_removal_is_not_bound_by_the_native_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Regression for PET-255: a stall past the reported native end still removes the root.
    import shutil

    from petasos.scanners._semgrep_process import CLEANUP_DEADLINE_OBSERVER

    original = shutil.rmtree

    def slow(path: Path, *args: Any, **kwargs: Any) -> None:
        if "psg-" in Path(path).name or "psg-" in str(path):
            time.sleep(0.4)
        original(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", slow)

    async def scan(*args: Any, **kwargs: Any) -> Any:
        root = Path(args[2])
        nested = root / "nested"
        nested.mkdir()
        (nested / "f.txt").write_text("x", encoding="utf-8")
        observer = CLEANUP_DEADLINE_OBSERVER.get()
        if observer is not None:
            observer(time.monotonic() - 5)
        return _finding()

    handle = _RuntimeHandle(monkeypatch, tmp_path)
    try:
        runtime = handle.start(scan)
        job = handle.submit()
        result = await _job_result(job, 3)
        assert result.error is None
        assert not runtime.failed
        assert job.root is None
        assert not list(handle.short.glob("psg-*"))
    finally:
        handle.stop()


async def test_retained_cleanup_failure_recovers_and_enqueues_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Regression for PET-255: a retained native failure can return the runtime to service.
    from petasos.scanners._semgrep_process import CleanupFailure

    child = _CleanChild(delay=0.3)

    async def scan(*args: Any, **kwargs: Any) -> Any:
        raise CleanupFailure(child)  # type: ignore[arg-type]

    handle = _RuntimeHandle(monkeypatch, tmp_path)
    try:
        runtime = handle.start(scan)
        job = handle.submit()
        result = await _job_result(job)
        assert result.error == "semgrep.cleanup_failed"
        await _wait_for(
            lambda: (
                (not runtime.failed)
                and child.closes == 1
                and "semgrep.probe_pending" in handle.enqueued
            )
        )
        with runtime.lock:
            assert job not in runtime.active
            assert job not in runtime.retained
        assert any(
            line == "kind=recovery outcome=recovered" for line in runtime.cleanup_diagnostics
        )
    finally:
        handle.stop()


async def test_recovery_waits_for_retained_worker_then_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from petasos.scanners._semgrep_engine import CpuCleanupFailure
    from petasos.scanners._semgrep_process import CleanupFailure

    child = _CleanChild()
    worker: concurrent.futures.Future[Any] = concurrent.futures.Future()

    async def scan(*args: Any, **kwargs: Any) -> Any:
        raise CpuCleanupFailure(worker, rt.error_result("semgrep.cleanup_failed"))

    handle = _RuntimeHandle(monkeypatch, tmp_path)
    try:
        runtime = handle.start(scan)
        job = handle.submit()
        await _job_result(job)
        await _wait_for(lambda: job in runtime.retained)
        assert not child.cleaned_calls
        assert "kind=native outcome=unfinished" in runtime._diagnostic_snapshot()
        late = CleanupFailure(child)  # type: ignore[arg-type]
        late.timings = {"leader_signalled": 0.5}
        worker.set_exception(late)
        await _wait_for(lambda: not runtime.failed and child.closes == 1)
        assert "semgrep.probe_pending" in handle.enqueued
        # Regression for PET-255 review: the late native failure's own evidence
        # reaches the snapshot, not only the initial "unfinished" line.
        assert "kind=native leader_signalled=0.500" in runtime._diagnostic_snapshot()
    finally:
        handle.stop()


async def test_recovery_is_running_when_the_failure_is_published(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Regression for PET-255 review: the recovery window starts before the
    # caller can observe cleanup_failed, not after the result is published.
    import threading

    from petasos.scanners._semgrep_engine import CpuCleanupFailure

    gate = threading.Event()
    worker: concurrent.futures.Future[Any] = concurrent.futures.Future()

    async def scan(*args: Any, **kwargs: Any) -> Any:
        while not gate.is_set():
            await asyncio.sleep(0.01)
        raise CpuCleanupFailure(worker, rt.error_result("semgrep.cleanup_failed"))

    handle = _RuntimeHandle(monkeypatch, tmp_path)
    try:
        runtime = handle.start(scan)
        job = handle.submit()
        seen: list[bool] = []
        # Runs synchronously inside set_result, on the runtime thread.
        job.future.add_done_callback(lambda _done: seen.append(runtime.recovery is not None))
        gate.set()
        await _job_result(job)
        assert seen == [True]
    finally:
        worker.set_result(None)
        handle.stop()


async def test_recovery_reads_the_removal_wrapper_not_the_executor_future(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Regression for PET-255 review: the executor future can be done while its
    # asyncio wrapper is not; reading the wrapper then must not end recovery.
    from petasos.scanners._semgrep_process import CleanupFailure

    child = _CleanChild(delay=0.3)

    async def scan(*args: Any, **kwargs: Any) -> Any:
        raise CleanupFailure(child)  # type: ignore[arg-type]

    handle = _RuntimeHandle(monkeypatch, tmp_path)
    try:
        runtime = handle.start(scan)
        job = handle.submit()
        await _job_result(job)
        real_wait = asyncio.wait
        stalled: list[int] = []

        import threading

        async def wait(fs: Any, *args: Any, **kwargs: Any) -> Any:
            on_runtime = threading.current_thread() is runtime.thread
            if on_runtime and job.removal is not None and not stalled:
                stalled.append(1)
                # Simulate the timeout landing just as the executor finishes:
                # the executor future is done, the wrapper not yet updated.
                end = time.perf_counter() + 2
                while job.removal is not None and not job.removal.done():
                    if time.perf_counter() > end:
                        break
                    time.sleep(0.005)
                return set(), set(fs)
            return await real_wait(fs, *args, **kwargs)

        monkeypatch.setattr(asyncio, "wait", wait)
        await _wait_for(lambda: not runtime.failed and child.closes == 1)
        assert stalled == [1]
        assert job.root is None
        assert not any("check_error" in line for line in runtime._diagnostic_snapshot())
    finally:
        handle.stop()


async def test_runtime_error_from_retained_worker_does_not_recover(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from petasos.scanners._semgrep_engine import CpuCleanupFailure

    jump = _jumping_clock(monkeypatch)
    worker: concurrent.futures.Future[Any] = concurrent.futures.Future()

    async def scan(*args: Any, **kwargs: Any) -> Any:
        raise CpuCleanupFailure(worker, rt.error_result("semgrep.cleanup_failed"))

    handle = _RuntimeHandle(monkeypatch, tmp_path)
    try:
        runtime = handle.start(scan)
        job = handle.submit()
        await _job_result(job)
        worker.set_exception(RuntimeError("synthetic"))
        jump["on"] = True
        await _wait_for(lambda: runtime.recovery is not None and runtime.recovery.done())
        assert runtime.failed
        assert rt._RECOVERIES == 0
        assert any("outcome=expired" in line for line in runtime.cleanup_diagnostics)
        assert job in runtime.retained
    finally:
        handle.stop()


async def test_unfinished_constructor_stays_failed_past_the_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from petasos.scanners._semgrep_engine import CpuCleanupFailure

    jump = _jumping_clock(monkeypatch)
    worker: concurrent.futures.Future[Any] = concurrent.futures.Future()

    async def scan(*args: Any, **kwargs: Any) -> Any:
        raise CpuCleanupFailure(worker, rt.error_result("semgrep.cleanup_failed"))

    handle = _RuntimeHandle(monkeypatch, tmp_path)
    try:
        runtime = handle.start(scan)
        handle.submit()
        await _wait_for(lambda: runtime.recovery is not None)
        jump["on"] = True
        await _wait_for(lambda: runtime.recovery is not None and runtime.recovery.done())
        assert runtime.failed
        assert not worker.done()
        assert any("outcome=expired" in line for line in runtime.cleanup_diagnostics)
    finally:
        worker.cancel()
        handle.stop()


async def test_late_removal_worker_does_not_submit_a_second_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import threading

    from petasos.scanners import _semgrep_roots as roots

    release = threading.Event()
    calls = {"n": 0}
    original = roots.remove_owned_root

    def blocked(root: Path) -> None:
        calls["n"] += 1
        assert release.wait(5)
        original(root)

    monkeypatch.setattr(roots, "remove_owned_root", blocked)
    monkeypatch.setattr(rt.Runtime, "_removal_deadline", lambda self, job, now: now + 0.1)

    async def scan(*args: Any, **kwargs: Any) -> Any:
        return _finding()

    handle = _RuntimeHandle(monkeypatch, tmp_path)
    try:
        runtime = handle.start(scan)
        job = handle.submit()
        await _wait_for(lambda: calls["n"] == 1 and runtime.failed)
        await asyncio.sleep(0.2)
        assert calls["n"] == 1
        release.set()
        await _wait_for(lambda: not runtime.failed and job.root is None)
        assert calls["n"] == 1
        assert "semgrep.probe_pending" in handle.enqueued
        assert any("outcome=unfinished" in line for line in runtime.cleanup_diagnostics)
    finally:
        release.set()
        handle.stop()


async def test_returned_worker_settles_without_touching_the_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from petasos.scanners._semgrep_engine import CpuCleanupFailure
    from petasos.scanners._semgrep_process import ProcessResult

    child = _CleanChild()
    worker: concurrent.futures.Future[Any] = concurrent.futures.Future()

    async def scan(*args: Any, **kwargs: Any) -> Any:
        raise CpuCleanupFailure(worker, rt.error_result("semgrep.cleanup_failed"))

    handle = _RuntimeHandle(monkeypatch, tmp_path)
    try:
        runtime = handle.start(scan)
        job = handle.submit()
        await _job_result(job)
        worker.set_result(ProcessResult(0, b"", None))
        await _wait_for(lambda: not runtime.failed and job.root is None)
        assert child.cleaned_calls == 0
        assert child.closes == 0
    finally:
        handle.stop()


async def test_closed_handle_is_not_polled_again_after_a_removal_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from petasos.scanners import _semgrep_roots as roots
    from petasos.scanners._semgrep_process import CleanupFailure

    child = _CleanChild(fail_after_close=True)
    calls = {"n": 0}
    original = roots.remove_owned_root

    def flaky(root: Path) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(13, "synthetic", None, 32)
        original(root)

    monkeypatch.setattr(roots, "remove_owned_root", flaky)

    async def scan(*args: Any, **kwargs: Any) -> Any:
        raise CleanupFailure(child)  # type: ignore[arg-type]

    handle = _RuntimeHandle(monkeypatch, tmp_path)
    try:
        runtime = handle.start(scan)
        job = handle.submit()
        await _job_result(job)
        await _wait_for(lambda: not runtime.failed and child.closes == 1)
        assert child.closes == 1
        assert calls["n"] == 2
        assert "semgrep.probe_pending" in handle.enqueued
    finally:
        handle.stop()


async def test_finished_removal_error_recovers_without_a_child_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from petasos.scanners import _semgrep_roots as roots

    child = _CleanChild()
    phase = {"fail": True}
    original = roots.remove_owned_root

    def flaky(root: Path) -> None:
        if phase["fail"]:
            raise PermissionError(13, "synthetic", None, 32)
        original(root)

    monkeypatch.setattr(roots, "remove_owned_root", flaky)

    async def scan(*args: Any, **kwargs: Any) -> Any:
        return _finding()

    handle = _RuntimeHandle(monkeypatch, tmp_path)
    try:
        runtime = handle.start(scan)
        job = handle.submit()
        await _job_result(job, 4)
        assert runtime.failed
        phase["fail"] = False
        await _wait_for(lambda: not runtime.failed and job.root is None)
        assert child.cleaned_calls == 0
        assert child.closes == 0
        assert not any("check_error" in line for line in runtime.cleanup_diagnostics)
        lines = list(runtime.cleanup_diagnostics)
        # OSError only takes the winerror argument on Windows.
        winerror = "32" if sys.platform == "win32" else "none"
        expected = f"kind=root_removal type=PermissionError errno=13 winerror={winerror}"
        assert expected in lines, lines
    finally:
        handle.stop()


async def test_removal_future_permission_error_is_retried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import threading

    from petasos.scanners import _semgrep_roots as roots

    release = threading.Event()
    calls = {"n": 0}
    original = roots.remove_owned_root

    def once(root: Path) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            assert release.wait(5)
            raise PermissionError(13, "synthetic", None, 32)
        original(root)

    monkeypatch.setattr(roots, "remove_owned_root", once)
    monkeypatch.setattr(rt.Runtime, "_removal_deadline", lambda self, job, now: now + 0.05)

    async def scan(*args: Any, **kwargs: Any) -> Any:
        return _finding()

    handle = _RuntimeHandle(monkeypatch, tmp_path)
    try:
        runtime = handle.start(scan)
        job = handle.submit()
        await _wait_for(lambda: calls["n"] == 1 and runtime.failed)
        release.set()
        await _wait_for(lambda: not runtime.failed and job.root is None)
        assert calls["n"] == 2
        assert not any("check_error" in line for line in runtime.cleanup_diagnostics)
    finally:
        release.set()
        handle.stop()


async def test_plain_cleanup_failure_does_not_read_a_worker_future(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from petasos.scanners._semgrep_process import CleanupFailure

    child = _CleanChild()

    async def scan(*args: Any, **kwargs: Any) -> Any:
        failure = CleanupFailure(child)  # type: ignore[arg-type]
        assert failure.child is child  # type: ignore[comparison-overlap]
        raise failure

    handle = _RuntimeHandle(monkeypatch, tmp_path)
    try:
        runtime = handle.start(scan)
        job = handle.submit()
        await _job_result(job)
        assert job.cpu_failure is None
        await _wait_for(lambda: not runtime.failed)
        assert job.failure is not None
    finally:
        handle.stop()


async def test_in_flight_removal_is_not_submitted_twice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import threading

    from petasos.scanners import _semgrep_roots as roots
    from petasos.scanners._semgrep_process import CleanupFailure

    release = threading.Event()
    calls = {"n": 0}
    original = roots.remove_owned_root

    def blocked(root: Path) -> None:
        calls["n"] += 1
        assert release.wait(5)
        original(root)

    monkeypatch.setattr(roots, "remove_owned_root", blocked)
    child = _CleanChild()

    async def scan(*args: Any, **kwargs: Any) -> Any:
        raise CleanupFailure(child)  # type: ignore[arg-type]

    handle = _RuntimeHandle(monkeypatch, tmp_path)
    try:
        runtime = handle.start(scan)
        handle.submit()
        await _wait_for(lambda: calls["n"] == 1)
        await asyncio.sleep(1.1)
        assert calls["n"] == 1
        release.set()
        await _wait_for(lambda: not runtime.failed)
        assert calls["n"] == 1
    finally:
        release.set()
        handle.stop()


async def test_check_error_on_one_job_does_not_stop_the_other(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import threading

    from petasos.scanners._semgrep_process import CleanupFailure

    jump = _jumping_clock(monkeypatch)
    go = threading.Event()
    good = _CleanChild()
    good.delay = 10**6

    class Bad:
        def cleaned(self) -> bool:
            raise OSError("synthetic poll")

        def close(self) -> None:
            return None

    bad = Bad()
    pending = [bad, good]
    gate = threading.Lock()

    async def scan(*args: Any, **kwargs: Any) -> Any:
        await asyncio.to_thread(go.wait, 2)
        with gate:
            child = pending.pop()
        raise CleanupFailure(child)  # type: ignore[arg-type]

    handle = _RuntimeHandle(monkeypatch, tmp_path)
    try:
        runtime = handle.start(scan)
        first = handle.submit()
        second = handle.submit()
        await _wait_for(lambda: len(runtime.active) == 2)
        go.set()
        await _job_result(first)
        await _job_result(second)
        await _wait_for(lambda: len(runtime.retained) == 2)
        good.delay = 0

        def retained_ids() -> list[int]:
            return [id(job.failure.child) for job in runtime.retained if job.failure is not None]

        await _wait_for(lambda: id(good) not in retained_ids())
        assert id(bad) in retained_ids()
        assert any(
            "outcome=check_error type=OSError" in line for line in runtime.cleanup_diagnostics
        )
        jump["on"] = True
        await _wait_for(lambda: runtime.recovery is not None and runtime.recovery.done())
        assert any("outcome=expired" in line for line in runtime.cleanup_diagnostics)
        assert runtime.failed
    finally:
        go.set()
        handle.stop()


async def test_recovery_cap_is_three_successes_per_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from petasos.scanners._semgrep_process import CleanupFailure

    async def scan(*args: Any, **kwargs: Any) -> Any:
        raise CleanupFailure(_CleanChild())  # type: ignore[arg-type]

    handle = _RuntimeHandle(monkeypatch, tmp_path)
    try:
        runtime = handle.start(scan)
        for _ in range(3):
            job = handle.submit()
            await _job_result(job)
            await _wait_for(lambda: not runtime.failed and runtime.availability_error is None)
        assert rt._RECOVERIES == 3
        previous = runtime.recovery
        job = handle.submit()
        await _job_result(job)
        assert runtime.failed
        assert runtime.recovery is previous
        assert previous is not None and previous.done()
        await asyncio.sleep(0.1)
        assert runtime.recovery is previous
    finally:
        handle.stop()


async def test_close_during_recovery_returns_failed_then_stops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from petasos.scanners._semgrep_process import CleanupFailure

    child = _CleanChild()
    child.delay = 10**6

    async def scan(*args: Any, **kwargs: Any) -> Any:
        failure = CleanupFailure(child)  # type: ignore[arg-type]
        failure.timings = {"leader_signalled": 0.41, "job_empty": None}
        raise failure

    handle = _RuntimeHandle(monkeypatch, tmp_path)
    try:
        runtime = handle.start(scan)
        assert handle.lease is not None
        job = handle.submit()
        await _job_result(job)
        await _wait_for(lambda: runtime.failed and runtime.recovery is not None)
        result = await rt.close_leases({handle.lease}, time.monotonic() + 1)
        assert result.status == "failed"
        assert result.reasons == ("cleanup_failed",)
        assert result.diagnostics
        assert "FIXTURE_SOURCE" not in " ".join(result.diagnostics)
        child.delay = 0
        await _wait_for(lambda: not runtime.thread.is_alive(), timeout=4)
    finally:
        handle.stop()


def _marker(root: Path, text: bytes | None = None) -> Path:
    path = root / "petasos-owner.json"
    path.write_bytes(text or b'{"schema":1,"pid":4,"born":1,"children":[]}')
    return path


def test_remove_owned_root_keeps_or_restores_the_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression for PET-255: a failed removal does not drop the owner marker.
    from petasos.scanners._semgrep_roots import remove_owned_root

    denied = tmp_path / "denied"
    denied.mkdir()
    marker = _marker(denied)
    original_marker = marker.read_bytes()
    (denied / "keep.txt").write_text("stay", encoding="utf-8")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked_marker = _marker(locked, b'{"schema":1,"kept":true}')
    locked_bytes = locked_marker.read_bytes()
    (locked / "gone.txt").write_text("x", encoding="utf-8")

    def refuse(path: Path) -> None:
        raise PermissionError("synthetic")

    with monkeypatch.context() as patch:
        patch.setattr(os, "unlink", refuse)
        with pytest.raises(PermissionError):
            remove_owned_root(denied)
    assert marker.read_bytes() == original_marker
    assert (denied / "keep.txt").is_file()

    def refuse_rmdir(path: Path) -> None:
        raise OSError("synthetic rmdir")

    with monkeypatch.context() as patch:
        patch.setattr(os, "rmdir", refuse_rmdir)
        with pytest.raises(OSError, match="rmdir"):
            remove_owned_root(locked)
    assert locked_marker.read_bytes() == locked_bytes
    assert not (locked / "gone.txt").exists()

    empty = tmp_path / "empty"
    empty.mkdir()
    remove_owned_root(empty)
    assert not empty.exists()
    remove_owned_root(denied)
    remove_owned_root(locked)
    assert not denied.exists()
    assert not locked.exists()


def test_recover_roots_leaves_a_marker_when_removal_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import psutil

    from petasos.scanners._semgrep_roots import recover_roots

    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: False)
    denied = tmp_path / "psg-perm0001"
    locked = tmp_path / "psg-rmdir001"
    denied.mkdir()
    locked.mkdir()
    denied_marker = _marker(denied)
    locked_marker = _marker(locked, b'{"schema":1,"pid":4,"born":1,"children":[]}')
    (denied / "keep.txt").write_text("stay", encoding="utf-8")
    (locked / "gone.txt").write_text("x", encoding="utf-8")
    mode = {"unlink": True}

    real_unlink = os.unlink
    real_rmdir = os.rmdir

    def unlink(path: Path) -> None:
        if (
            mode["unlink"]
            and Path(path).parent.name == "psg-perm0001"
            and Path(path).name != "petasos-owner.json"
        ):
            raise PermissionError("synthetic")
        real_unlink(path)

    def rmdir(path: Path) -> None:
        if Path(path) == locked and mode["unlink"]:
            raise OSError("synthetic rmdir")
        real_rmdir(path)

    monkeypatch.setattr(os, "unlink", unlink)
    monkeypatch.setattr(os, "rmdir", rmdir)
    assert recover_roots() == 0
    assert denied_marker.is_file()
    assert (denied / "keep.txt").is_file()
    assert locked_marker.read_bytes() == b'{"schema":1,"pid":4,"born":1,"children":[]}'
    mode["unlink"] = False
    assert recover_roots() == 2
    assert not denied.exists()
    assert not locked.exists()


def test_marker_guards_refuse_without_reading_or_unlinking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import stat

    from petasos.scanners._semgrep_roots import remove_owned_root

    opened: list[str] = []
    real_open = Path.open

    def spy(self: Path, *args: Any, **kwargs: Any) -> Any:
        opened.append(str(self))
        return real_open(self, *args, **kwargs)

    root = tmp_path / "linked"
    root.mkdir()
    target = tmp_path / "secret.txt"
    target.write_bytes(b"SECRET_TARGET_BYTES")
    marker = root / "petasos-owner.json"
    try:
        os.symlink(target, marker)
    except OSError:
        pytest.skip("symlink not permitted")
    # Spy only across the call under test: the fixture's own write/read of the
    # target also go through Path.open and must not count as a removal read.
    monkeypatch.setattr(Path, "open", spy)
    with pytest.raises(OSError, match="marker_refused"):
        remove_owned_root(root)
    monkeypatch.setattr(Path, "open", real_open)
    assert opened == []
    assert marker.is_symlink()
    assert target.read_bytes() == b"SECRET_TARGET_BYTES"

    grown = tmp_path / "grown"
    grown.mkdir()
    grown_marker = _marker(grown, b"x" * 20000)
    before = grown_marker.stat().st_size
    real_stat = os.stat

    class Small:
        st_mode = stat.S_IFREG
        st_size = 10
        st_file_attributes = 0

    def small(path: Path, *args: Any, **kwargs: Any) -> Any:
        if Path(path).name == "petasos-owner.json":
            return Small()
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", small)
    with pytest.raises(OSError, match="marker_refused"):
        remove_owned_root(grown)
    monkeypatch.undo()
    assert grown_marker.is_file()
    assert grown_marker.stat().st_size == before


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction")
def test_reparse_point_marker_is_not_unlinked(tmp_path: Path) -> None:
    import subprocess

    from petasos.scanners._semgrep_roots import remove_owned_root

    root = tmp_path / "junction-root"
    root.mkdir()
    target = tmp_path / "junction-target"
    target.mkdir()
    (target / "secret.txt").write_text("SECRET_TARGET_BYTES", encoding="utf-8")
    marker = root / "petasos-owner.json"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(marker), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip("junction not permitted")
    with pytest.raises(OSError, match="marker_refused"):
        remove_owned_root(root)
    assert marker.exists()
    assert (target / "secret.txt").read_text(encoding="utf-8") == "SECRET_TARGET_BYTES"


def test_linked_root_is_refused_without_touching_its_target(tmp_path: Path) -> None:
    # Regression for PET-255 review: scandir follows a root replaced by a link;
    # shutil.rmtree refused one, so remove_owned_root must refuse it too.
    import subprocess

    from petasos.scanners._semgrep_roots import remove_owned_root

    target = tmp_path / "outside"
    target.mkdir()
    (target / "keep.txt").write_text("OUTSIDE", encoding="utf-8")
    (target / "petasos-owner.json").write_text('{"schema": 1}', encoding="utf-8")
    root = tmp_path / "psg-linked0"
    if sys.platform == "win32":
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(root), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if made.returncode != 0:
            pytest.skip("junction not permitted")
    else:
        os.symlink(target, root, target_is_directory=True)
    with pytest.raises(OSError, match="root_not_owned"):
        remove_owned_root(root)
    assert (target / "keep.txt").read_text(encoding="utf-8") == "OUTSIDE"
    assert (target / "petasos-owner.json").is_file()


def test_oversized_marker_is_not_unlinked(tmp_path: Path) -> None:
    from petasos.scanners._semgrep_roots import remove_owned_root

    root = tmp_path / "huge"
    root.mkdir()
    marker = _marker(root, b"x" * 16385)
    with pytest.raises(OSError, match="marker_refused"):
        remove_owned_root(root)
    assert marker.read_bytes() == b"x" * 16385


async def test_paused_creator_fails_closed_without_retention(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Regression for PET-255: a root removed before its marker write is not retained.
    from petasos.scanners._semgrep_roots import recover_roots
    from petasos.scanners._semgrep_source import Selection

    monkeypatch.setattr("petasos.scanners._semgrep_roots.MARKERLESS_MIN_AGE", 0)
    original = Path.write_text
    removed: list[int] = []
    write_errors: list[BaseException] = []

    def write(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        if self.name == "petasos-owner.json":
            past = time.time() - 2
            os.utime(self.parent, (past, past))
            removed.append(recover_roots())
        try:
            return original(self, data, encoding=encoding, errors=errors, newline=newline)
        except OSError as exc:
            write_errors.append(exc)
            raise

    monkeypatch.setattr(Path, "write_text", write)
    scans: list[int] = []

    async def scan(*args: Any, **kwargs: Any) -> Any:
        # Recorded outside the runtime: _execute would turn a raise here into
        # the same engine_unavailable result this test expects.
        scans.append(1)
        return _finding()

    handle = _RuntimeHandle(monkeypatch, tmp_path)
    try:
        runtime = handle.start(scan)
        assert handle.lease is not None
        job = runtime.submit(
            handle.lease, Selection(), time.monotonic() + 30, source=("eval(data)", None, None)
        )
        result = await _job_result(job)
        assert result.error == "semgrep.engine_unavailable"
        # Marker-less recovery removed the live root, so the marker write failed
        # and the request never reached the engine.
        assert removed == [1]
        assert len(write_errors) == 1 and isinstance(write_errors[0], FileNotFoundError)
        assert scans == []
        assert not runtime.failed
        assert not runtime.retained
        assert job not in runtime.active
    finally:
        handle.stop()


async def test_cleanup_diagnostics_are_bounded_and_lock_the_close_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Regression for PET-255: diagnostic lines stay source-free and the deque holds eight.
    import threading

    from petasos.scanners._semgrep_process import CleanupFailure

    root_text = str(tmp_path)
    child = _CleanChild()
    child._last_cleanup_state = {  # type: ignore[attr-defined]
        "leader_signalled": True,
        "active": 1,
        "total": 2,
        "images": {1: "semgrep-core.exe"},
    }

    async def scan(*args: Any, **kwargs: Any) -> Any:
        failure = CleanupFailure(child)  # type: ignore[arg-type]
        failure.timings = {
            "leader_signalled": 0.41,
            "job_empty": None,
            "descendants_signalled": None,
        }
        failure.tracked = ((7, 1.5),)
        raise failure

    handle = _RuntimeHandle(monkeypatch, tmp_path)
    try:
        runtime = handle.start(scan)
        rt._RECOVERIES = rt.RECOVERY_LIMIT
        job = handle.submit()
        await _job_result(job)
        line = next(item for item in runtime.cleanup_diagnostics if item.startswith("kind=native"))
        allowed = {
            "kind",
            "leader_signalled",
            "job_empty",
            "descendants_signalled",
            "group_signalled",
            "reaped",
            "active",
            "total",
            "images",
            "type",
            "errno",
            "winerror",
            "outcome",
        }
        for token in line.split():
            assert token.split("=", 1)[0] in allowed
        assert root_text not in line
        assert "FIXTURE_SOURCE" not in line
        assert "leader_signalled=" in line
        assert job.failure is not None and job.failure.tracked == ((7, 1.5),)
        for index in range(10):
            runtime._append_diagnostic(f"kind=recovery outcome=expired n={index}")
        assert len(runtime.cleanup_diagnostics) == 8
        assert handle.lease is not None
        runtime.failed = True
        stop = threading.Event()

        def append() -> None:
            while not stop.is_set():
                runtime._append_diagnostic("kind=recovery outcome=recovered")

        thread = threading.Thread(target=append)
        thread.start()
        try:
            result = await rt.close_leases({handle.lease}, time.monotonic() + 1)
        finally:
            stop.set()
            thread.join(2)
        assert result.status == "failed"
        assert result.diagnostics
    finally:
        handle.stop()
