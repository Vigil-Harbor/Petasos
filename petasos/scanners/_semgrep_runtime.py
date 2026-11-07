"""One bounded, loop-independent owner for local Semgrep jobs.

All admissions are protected by a short threading lock. Child work belongs to
the control loop, never to a caller's loop or a default-executor work queue.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import math
import os
import shutil
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from petasos._coverage import ScanCoverage
from petasos._types import ScanResult
from petasos.scanners._semgrep_engine import (
    ENGINE_VERSION,
    CpuCleanupFailure,
    await_cpu,
    result_for,
    scan_selected,
)
from petasos.scanners._semgrep_process import (
    CHILD_OBSERVER,
    CLEANUP_DEADLINE_OBSERVER,
    CleanupFailure,
    run_process,
)
from petasos.scanners._semgrep_source import Selection, select_sources


@dataclass(frozen=True)
class SemgrepCloseResult:
    status: Literal["closed", "failed", "timed_out"]
    cleanup_seconds: float = 0
    join_seconds: float = 0
    leases: int = 0
    jobs: int = 0
    children: int = 0
    source_roots: int = 0
    readers: int = 0
    manager_threads: int = 0
    reasons: tuple[str, ...] = ()


class SemgrepCleanupError(RuntimeError):
    def __init__(self, result: SemgrepCloseResult) -> None:
        super().__init__("Semgrep owned cleanup did not complete")
        self.result = result


@dataclass(frozen=True)
class Settings:
    engine: str
    digest: str
    timeout: float = 8.0
    max_bytes: int = 131072

    @property
    def identity(self) -> tuple[str, str]:
        return os.path.normcase(os.path.abspath(self.engine)), self.digest.lower()


def error_result(code: str, total: int = 0) -> ScanResult:
    return ScanResult("semgrep", (), 0, code, ScanCoverage("error", total, 0, 0, 0))


async def remove_root(
    root: Path,
    executor: concurrent.futures.ThreadPoolExecutor,
    deadline: float,
    outcome: ScanResult,
) -> None:
    """Retry transient file locks within the remaining child/file cleanup budget."""
    while True:
        worker = executor.submit(shutil.rmtree, root)
        waiting = asyncio.wrap_future(worker)
        await asyncio.wait({waiting}, timeout=max(0, deadline - time.monotonic()))
        if not waiting.done():
            waiting.add_done_callback(
                lambda done: done.exception() if not done.cancelled() else None
            )
            raise CpuCleanupFailure(worker, outcome)
        try:
            waiting.result()
            return
        except FileNotFoundError:
            if not root.exists():
                return
        except OSError:
            pass
        if time.monotonic() >= deadline:
            raise OSError("semgrep.cleanup_failed")
        await asyncio.sleep(min(0.02, max(0, deadline - time.monotonic())))


@dataclass(eq=False)
class Lease:
    runtime: Runtime
    settings: Settings
    key: object
    closed: bool = False
    # Token objects expose synchronous close, without awaiting an abandoned caller.
    tokens: set[object] = field(default_factory=set)
    scheduling_identity: object | None = None


@dataclass(eq=False)
class Job:
    lease: Lease | None
    key: object
    selection: Selection | None
    deadline: float
    timeout: float
    future: concurrent.futures.Future[ScanResult] = field(
        default_factory=concurrent.futures.Future
    )
    cancelled: threading.Event = field(default_factory=threading.Event)
    root: Path | None = None
    failure: CleanupFailure | None = None
    child: Any = None
    cpu_failure: CpuCleanupFailure | None = None
    task: asyncio.Task[None] | None = None
    expiry: asyncio.TimerHandle | None = None
    source: tuple[str, tuple[tuple[int, int], ...] | None, int | None] | None = None
    refusal: str | None = None
    cleanup_deadline: float | None = None


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.lock = threading.RLock()
        self.leases: set[Lease] = set()
        self.pending: dict[object, deque[Job]] = {}
        self.turns: deque[object] = deque()
        self.active: set[Job] = set()
        self.failed = False
        self.stopping = False
        self.close_started: float | None = None
        self.cleanup_finished: float | None = None
        self.stopped_at: float | None = None
        self.availability_error: str | None = "semgrep.probe_pending"
        self.probe: Job | None = None
        self.retry: asyncio.TimerHandle | None = None
        self.retry_count = 0
        self.identity_stat: tuple[int, int, int, int, int] | None = None
        self.identity_checked_at = 0.0
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="petasos-semgrep-cpu"
        )
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="petasos-semgrep", daemon=True)
        self.ready = threading.Event()
        self.thread.start()
        self.ready.wait()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.ready.set()
        try:
            self.loop.run_forever()
        finally:
            self.executor.shutdown(wait=True)
            self.loop.close()
            self.stopped_at = time.monotonic()

    def register(
        self, settings: Settings, key: object, scheduling_identity: object | None = None
    ) -> Lease | str:
        with self.lock:
            if self.stopping or self.failed:
                return "semgrep.engine_unavailable"
            if settings.identity != self.settings.identity:
                return "semgrep.engine_identity_conflict"
            if len(self.leases) >= 12:
                return "semgrep.lease_exhausted"
            lease = Lease(self, settings, key, scheduling_identity=scheduling_identity)
            self.leases.add(lease)
            if self.probe is None and self.availability_error == "semgrep.probe_pending":
                self._enqueue_probe()
            return lease

    def _enqueue_probe(self) -> None:
        job = Job(None, self, None, time.monotonic() + 6, 6)
        self.probe = job
        self._enqueue(job)

    def _enqueue(self, job: Job) -> None:
        if job.key not in self.pending:
            self.pending[job.key] = deque()
            self.turns.append(job.key)
        self.pending[job.key].append(job)
        self.loop.call_soon_threadsafe(self._schedule, job)

    def _schedule(self, job: Job) -> None:
        with self.lock:
            if not job.future.done() and job in self.pending.get(job.key, ()):
                job.expiry = self.loop.call_later(
                    max(0, job.deadline - min(1.5, 0.75 * job.timeout) - time.monotonic()),
                    self._expire,
                    job,
                )
            self._pump()

    def _expire(self, job: Job) -> None:
        with self.lock:
            queue = self.pending.get(job.key)
            if queue is None or job not in queue:
                return
            self._remove_pending(job, "semgrep.queue_deadline")
            self._pump()

    def _remove_pending(self, job: Job, code: str) -> None:
        queue = self.pending[job.key]
        queue.remove(job)
        if not queue:
            del self.pending[job.key]
            self.turns.remove(job.key)
        self._finish_pending(job, code)

    def _finish_pending(self, job: Job, code: str) -> None:
        if job.expiry is not None:
            job.expiry.cancel()
        if job is self.probe:
            self.probe = None
            self.availability_error = code
            if self.leases and not self.stopping and not self.failed:
                self.retry = self.loop.call_later(30, self._retry_probe)
        result = result_for(job.selection or Selection(), error=code)
        job.selection = None
        job.source = None
        if not job.future.done():
            job.future.set_result(result)

    def submit(
        self,
        lease: Lease,
        selection: Selection,
        deadline: float,
        *,
        source: tuple[str, tuple[tuple[int, int], ...] | None, int | None] | None = None,
        refusal: str | None = None,
    ) -> Job:
        job = Job(
            lease,
            lease.key,
            selection,
            deadline,
            lease.settings.timeout,
            source=source,
            refusal=refusal,
        )
        with self.lock:
            code = None
            if lease.closed:
                code = "semgrep.lease_closed"
            elif self.failed or self.stopping:
                code = "semgrep.engine_unavailable"
            elif self.availability_error and source is None:
                code = self.availability_error
            elif len(self.active) + sum(map(len, self.pending.values())) >= 12:
                code = "semgrep.queue_full"
            if code:
                job.source = None
                job.selection = None
                job.future.set_result(result_for(selection, error=code))
            else:
                self._enqueue(job)
        return job

    def cancel(self, job: Job) -> None:
        with self.lock:
            job.cancelled.set()
            queue = self.pending.get(job.key)
            if queue is not None and job in queue:
                self._remove_pending(job, "semgrep.cancelled")

    def _pump(self) -> None:
        with self.lock:
            while not self.failed and len(self.active) < 2 and self.turns:
                key = self.turns.popleft()
                queue = self.pending[key]
                job = queue.popleft()
                if queue:
                    self.turns.append(key)
                else:
                    del self.pending[key]
                if job.cancelled.is_set():
                    self._finish_pending(job, "semgrep.cancelled")
                    continue
                if job.deadline - time.monotonic() < min(1.5, 0.75 * job.timeout):
                    self._finish_pending(job, "semgrep.queue_deadline")
                    continue
                if job.expiry is not None:
                    job.expiry.cancel()
                self.active.add(job)
                job.task = self.loop.create_task(self._execute(job))
            self._stop_if_empty()

    def _verify_identity(self) -> None:
        if self.identity_stat is None:
            from petasos.scanners._semgrep_roots import recover_roots

            recover_roots()
        path = Path(self.settings.engine)
        stat = path.stat()
        identity = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if identity == self.identity_stat and time.monotonic() - self.identity_checked_at < 30:
            return
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != self.settings.digest.lower():
            raise ValueError("semgrep.engine_integrity")
        self.identity_stat = identity
        self.identity_checked_at = time.monotonic()

    def _new_root(self, job: Job) -> Path:
        import psutil

        root = Path(tempfile.mkdtemp(prefix="psg-"))
        job.root = root
        # OCaml socketpair on Windows needs room for a socket name after TMP.
        # Fail visibly rather than letting an obscure engine error masquerade
        # as unsupported source. Root remains owned until removal succeeds.
        marker = {
            "schema": 1,
            "pid": os.getpid(),
            "born": psutil.Process().create_time(),
            "children": [],
        }
        (root / "petasos-owner.json").write_text(json.dumps(marker), encoding="utf-8")
        return root

    async def _execute(self, job: Job) -> None:
        outcome = error_result("semgrep.engine_unavailable")
        retain = False

        def observe(child: Any) -> None:
            import psutil

            with self.lock:
                job.child = child
            if child is not None and job.root is not None:
                marker_path = job.root / "petasos-owner.json"
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
                try:
                    marker["children"].append(
                        {"pid": child.pid, "born": psutil.Process(child.pid).create_time()}
                    )
                except psutil.NoSuchProcess:
                    return
                marker_path.write_text(json.dumps(marker), encoding="utf-8")

        observer_token = CHILD_OBSERVER.set(observe)
        cleanup_token = CLEANUP_DEADLINE_OBSERVER.set(
            lambda deadline: setattr(job, "cleanup_deadline", deadline)
        )
        try:
            if job.source is not None:
                text, segments, total = job.source
                assert job.lease is not None
                try:
                    job.selection = await select_sources(
                        text,
                        segments=segments,
                        total=total,
                        max_bytes=job.lease.settings.max_bytes,
                    )
                finally:
                    job.source = None
                    del text
                if not job.selection.targets:
                    outcome = result_for(job.selection)
                    return
                with self.lock:
                    unavailable = job.refusal or self.availability_error
                if unavailable:
                    outcome = result_for(job.selection, error=unavailable)
                    return
            verification = await await_cpu(
                self.executor.submit(self._verify_identity),
                job.deadline,
                job.cancelled,
                result_for(job.selection or Selection(), error="semgrep.cleanup_failed"),
            )
            cpu_error = verification.error
            if cpu_error:
                outcome = result_for(
                    job.selection or Selection(),
                    error=(
                        "semgrep.queue_deadline"
                        if cpu_error.startswith("ScannerTimeout:")
                        else cpu_error
                    ),
                )
            elif job.cancelled.is_set():
                outcome = result_for(job.selection or Selection(), error="semgrep.cancelled")
            elif job.deadline - time.monotonic() < min(1.5, 0.75 * job.timeout):
                outcome = result_for(job.selection or Selection(), error="semgrep.queue_deadline")
            else:
                job.root = self._new_root(job)
                if os.name == "nt" and len(str(job.root).encode("utf-8")) > 80:
                    raise ValueError("semgrep.temp_path_limit")
                if job.selection is None:
                    version = await run_process(
                        [self.settings.engine, "-version"], job.root, job.deadline, job.cancelled
                    )
                    if version.error:
                        outcome = error_result(version.error)
                    elif version.returncode != 0 or not version.stdout.decode(
                        "utf-8"
                    ).strip().startswith("semgrep-core version: " + ENGINE_VERSION + " "):
                        outcome = error_result("semgrep.engine_version")
                    else:
                        selected = await select_sources("```python\neval(petasos_probe)\n```")
                        outcome = await scan_selected(
                            selected,
                            self.settings.engine,
                            job.root,
                            job.deadline,
                            job.cancelled,
                            self.executor,
                        )
                        if outcome.error is None and not outcome.findings:
                            outcome = error_result("semgrep.probe_failed")
                else:
                    outcome = await scan_selected(
                        job.selection,
                        self.settings.engine,
                        job.root,
                        job.deadline,
                        job.cancelled,
                        self.executor,
                    )
        except CpuCleanupFailure as exc:
            job.cpu_failure = exc
            retain = True
            outcome = exc.outcome
        except CleanupFailure as exc:
            job.failure = exc
            retain = True
            outcome = error_result("semgrep.cleanup_failed")
        except ValueError as exc:
            code = str(exc)
            if code == "semgrep.engine_integrity":
                with self.lock:
                    self.availability_error = code
            outcome = error_result(
                code
                if code
                in (
                    "semgrep.engine_integrity",
                    "semgrep.engine_version",
                    "semgrep.temp_path_limit",
                )
                else "semgrep.engine_error"
            )
        except Exception:
            outcome = error_result("semgrep.engine_unavailable")
        finally:
            CHILD_OBSERVER.reset(observer_token)
            CLEANUP_DEADLINE_OBSERVER.reset(cleanup_token)
            if job.root is not None and not retain:
                try:
                    await remove_root(
                        job.root,
                        self.executor,
                        job.cleanup_deadline or time.monotonic() + 2,
                        result_for(job.selection or Selection(), error="semgrep.cleanup_failed"),
                    )
                    job.root = None
                except CpuCleanupFailure as exc:
                    job.cpu_failure = exc
                    retain = True
                    outcome = exc.outcome
                except OSError:
                    retain = True
                    outcome = error_result("semgrep.cleanup_failed")
            with self.lock:
                if retain:
                    self.failed = True
                    self.availability_error = "semgrep.cleanup_failed"
                else:
                    self.active.discard(job)
                if job.selection is None:
                    self.probe = None
                    self.availability_error = outcome.error
                    permanent = outcome.error in (
                        "semgrep.engine_integrity",
                        "semgrep.engine_version",
                        "semgrep.temp_path_limit",
                        "semgrep.cleanup_failed",
                    )
                    if outcome.error and not permanent and self.leases and not self.stopping:
                        delay = (30, 60, 120)[self.retry_count] if self.retry_count < 3 else 300
                        self.retry_count += 1
                        self.retry = self.loop.call_later(delay, self._retry_probe)
                if (
                    job.selection is not None
                    and outcome.error
                    and (outcome.coverage is None or outcome.coverage.target_count == 0)
                ):
                    outcome = result_for(job.selection, error=outcome.error)
                job.selection = None  # Terminal objects retain no submitted source.
                job.source = None
                if not job.future.done():
                    job.future.set_result(outcome)
                if self.failed:
                    for queue in tuple(self.pending.values()):
                        for pending in tuple(queue):
                            self.cancel(pending)
                self._pump()

    def _retry_probe(self) -> None:
        with self.lock:
            self.retry = None
            if self.leases and not self.stopping and not self.failed:
                if len(self.active) + sum(map(len, self.pending.values())) >= 12:
                    self.retry = self.loop.call_later(1, self._retry_probe)
                    return
                self.availability_error = "semgrep.probe_pending"
                self._enqueue_probe()

    def close_leases(self, leases: set[Lease]) -> None:
        with self.lock:
            for lease in leases:
                lease.closed = True
                for token in tuple(lease.tokens):
                    token._retire()  # type: ignore[attr-defined]
                self.leases.discard(lease)
            for job in [*self.active, *(j for q in self.pending.values() for j in q)]:
                if job.lease in leases or (job.lease is None and not self.leases):
                    self.cancel(job)
            if not self.leases:
                self.stopping = True
                if self.close_started is None:
                    self.close_started = time.monotonic()
                self.loop.call_soon_threadsafe(self._stop_if_empty)

    def _stop_if_empty(self) -> None:
        if self.stopping and not self.leases and not self.active and not self.pending:
            if self.retry is not None:
                self.retry.cancel()
                self.retry = None
            if self.cleanup_finished is None:
                self.cleanup_finished = time.monotonic()
            self.loop.stop()

    def residuals(self, leases: set[Lease] | None = None) -> dict[str, int]:
        with self.lock:
            jobs = [*self.active, *(j for q in self.pending.values() for j in q)]
            if leases is not None:
                jobs = [
                    j for j in jobs if j.lease in leases or (j.lease is None and not self.leases)
                ]
            return {
                "leases": len(self.leases if leases is None else self.leases & leases),
                "jobs": len(jobs),
                "children": sum(j.child is not None or j.failure is not None for j in jobs),
                "source_roots": sum(j.root is not None for j in jobs),
                "readers": 0,
                "manager_threads": int(self.thread.is_alive())
                if not self.leases or leases is None
                else 0,
            }


_GLOBAL_LOCK = threading.RLock()
_RUNTIME: Runtime | None = None
_SEALED = False


def acquire(
    settings: Settings, key: object, *, scheduling_identity: object | None = None
) -> Lease | str:
    global _RUNTIME
    with _GLOBAL_LOCK:
        if _SEALED:
            return "semgrep.runtime_closed"
        if _RUNTIME is not None and not _RUNTIME.thread.is_alive() and not _RUNTIME.failed:
            _RUNTIME = None
        if _RUNTIME is None:
            _RUNTIME = Runtime(settings)
        return _RUNTIME.register(settings, key, scheduling_identity)


async def await_job(job: Job) -> ScanResult:
    future = asyncio.wrap_future(job.future)
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        runtime = job.lease.runtime if job.lease is not None else None
        if runtime is not None:
            runtime.cancel(job)
        # Repeated caller cancellation cannot cancel or detach owned cleanup.
        while not future.done():
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError:
                continue
        raise


async def close_leases(leases: set[Lease], deadline: float) -> SemgrepCloseResult:
    start = time.monotonic()
    if not math.isfinite(deadline):
        raise ValueError("Semgrep close deadline must be finite")
    deadline = min(deadline, start + 3)
    runtimes = {lease.runtime for lease in leases}
    if not runtimes:
        return SemgrepCloseResult("closed")
    for runtime in runtimes:
        if runtime.thread.is_alive():
            runtime.close_leases(leases)
    while True:
        residual = {
            name: sum(r.residuals(leases)[name] for r in runtimes)
            for name in (
                "leases",
                "jobs",
                "children",
                "source_roots",
                "readers",
                "manager_threads",
            )
        }
        if not any(residual.values()):
            return SemgrepCloseResult("closed", cleanup_seconds=time.monotonic() - start)
        if any(r.failed for r in runtimes):
            return SemgrepCloseResult(
                "failed",
                cleanup_seconds=time.monotonic() - start,
                **residual,
                reasons=("cleanup_failed",),
            )
        if time.monotonic() >= deadline:
            break
        try:
            await asyncio.sleep(min(0.01, max(0, deadline - time.monotonic())))
        except asyncio.CancelledError:
            # Closure was already initiated; finish its bounded observation.
            continue
    residual = {
        name: sum(r.residuals(leases)[name] for r in runtimes)
        for name in ("leases", "jobs", "children", "source_roots", "readers", "manager_threads")
    }
    return SemgrepCloseResult(
        "timed_out",
        cleanup_seconds=time.monotonic() - start,
        **residual,
        reasons=("close_deadline",),
    )


def close_semgrep_runtime(*, deadline: float) -> SemgrepCloseResult:
    global _SEALED
    start = time.monotonic()
    if not math.isfinite(deadline):
        raise ValueError("Semgrep close deadline must be finite")
    deadline = min(deadline, start + 3)
    with _GLOBAL_LOCK:
        _SEALED = True
        runtime = _RUNTIME
        if runtime is None:
            return SemgrepCloseResult("closed")
        if threading.current_thread() is runtime.thread:
            return SemgrepCloseResult(
                "failed", reasons=("control_thread_close",), **runtime.residuals()
            )
        if runtime.thread.is_alive():
            runtime.close_leases(set(runtime.leases))
    if not runtime.failed:
        runtime.thread.join(timeout=max(0, deadline - time.monotonic()))
    residual = runtime.residuals()
    status: Literal["closed", "failed", "timed_out"] = (
        "failed" if runtime.failed else "timed_out" if any(residual.values()) else "closed"
    )
    return SemgrepCloseResult(
        status,
        cleanup_seconds=max(
            0, (runtime.cleanup_finished or time.monotonic()) - (runtime.close_started or start)
        ),
        join_seconds=max(0, (runtime.stopped_at or time.monotonic()) - runtime.cleanup_finished)
        if runtime.cleanup_finished
        else 0,
        **residual,
        reasons=()
        if status == "closed"
        else ("cleanup_failed" if runtime.failed else "close_deadline",),
    )
