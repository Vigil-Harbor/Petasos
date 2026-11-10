"""One bounded, loop-independent owner for local Semgrep jobs.

All admissions are protected by a short threading lock. Native lifecycle work
uses the two owned workers, never a caller's loop or a default-executor queue.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import math
import os
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from petasos._coverage import ScanCoverage
from petasos._types import ScanResult
from petasos.scanners import _semgrep_roots as roots
from petasos.scanners._semgrep_engine import (
    ENGINE_VERSION,
    CpuCleanupFailure,
    await_cpu,
    result_for,
    run_owned_process,
    scan_selected,
)
from petasos.scanners._semgrep_process import (
    CHILD_OBSERVER,
    CleanupFailure,
)
from petasos.scanners._semgrep_source import Selection, select_sources

REMOVAL_MIN_ATTEMPT = 0.25
RECOVERY_WINDOW = 30.0
RECOVERY_LIMIT = 3
_RECOVERY_POLL = 0.05
_RECOVERIES = 0
_RECOVERIES_LOCK = threading.Lock()


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
    diagnostics: tuple[str, ...] = ()


class SemgrepCleanupError(RuntimeError):
    def __init__(self, result: SemgrepCloseResult) -> None:
        super().__init__("Semgrep owned cleanup did not complete")
        self.result = result


@dataclass(frozen=True)
class Settings:
    engine: str
    digest: str
    timeout: float = 8.0
    max_bytes: int = 65536

    @property
    def identity(self) -> tuple[str, str]:
        return os.path.normcase(os.path.abspath(self.engine)), self.digest.lower()


def error_result(code: str, total: int = 0) -> ScanResult:
    return ScanResult("semgrep", (), 0, code, ScanCoverage("error", total, 0, 0, 0))


def _oserror_line(exc: BaseException | None) -> str:
    if not isinstance(exc, OSError):
        return "kind=root_removal type=none errno=none winerror=none"
    errno = "none" if exc.errno is None else str(exc.errno)
    win = getattr(exc, "winerror", None)
    winerror = "none" if win is None else str(win)
    return f"kind=root_removal type={type(exc).__name__} errno={errno} winerror={winerror}"


def _native_line(exc: CleanupFailure) -> str:
    parts = ["kind=native"]
    for key in (
        "leader_signalled",
        "job_empty",
        "descendants_signalled",
        "group_signalled",
        "reaped",
    ):
        if key in exc.timings:
            value = exc.timings[key]
            parts.append(f"{key}={'none' if value is None else format(value, '.3f')}")
    state = exc.state if isinstance(exc.state, dict) else {}
    for key in ("active", "total"):
        if isinstance(state.get(key), int) and not isinstance(state.get(key), bool):
            parts.append(f"{key}={state[key]}")
    images = state.get("images")
    if isinstance(images, dict):
        names = [
            value.replace("\\", "/").rsplit("/", 1)[-1]
            for value in images.values()
            if isinstance(value, str) and value
        ]
        if names:
            parts.append("images=" + ",".join(names))
    return " ".join(parts)


def _tracked_clear(tracked: tuple[tuple[int, float], ...]) -> bool:
    import psutil

    for pid, born in tracked:
        try:
            proc = psutil.Process(pid)
            alive = proc.is_running() and proc.create_time() == born
            if alive and proc.status() != psutil.STATUS_ZOMBIE:
                return False
        except psutil.NoSuchProcess:
            continue
    return True


def _recovery_allowed() -> bool:
    with _RECOVERIES_LOCK:
        return _RECOVERIES < RECOVERY_LIMIT


async def remove_root(
    root: Path,
    executor: concurrent.futures.ThreadPoolExecutor,
    deadline: float,
    outcome: ScanResult,
) -> None:
    """Retry transient file locks within the removal budget."""
    last_error: OSError | None = None
    while True:
        # A finished error is the deadline's result. Do not start an attempt
        # that has no time left and would hide that error.
        if last_error is not None and time.monotonic() >= deadline:
            raise OSError("semgrep.cleanup_failed") from last_error
        # Looked up on the module so the benchmark wrapper is the one that runs.
        worker = executor.submit(roots.remove_owned_root, root)
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
        except FileNotFoundError as exc:
            if not root.exists():
                return
            last_error = exc
        except OSError as exc:
            last_error = exc
        if time.monotonic() >= deadline:
            failure = OSError("semgrep.cleanup_failed")
            if last_error is not None:
                raise failure from last_error
            raise failure
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
    cancelled_at: float | None = None
    removal: concurrent.futures.Future[None] | None = None
    removal_wait: asyncio.Future[None] | None = None
    native_settled: bool = False
    unconfirmable: bool = False
    removal_error_types: set[str] = field(default_factory=set)


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
        self.retained: set[Job] = set()
        self.recovery: asyncio.Task[None] | None = None
        self.recovery_expired = False
        self.cleanup_diagnostics: deque[str] = deque(maxlen=8)
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
            if not job.cancelled.is_set():
                job.cancelled_at = time.monotonic()
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

    def _removal_deadline(self, job: Job, now: float) -> float:
        budget = now + 2.0
        if job.cancelled_at is not None:
            budget = min(budget, min(job.cancelled_at, job.deadline) + 4.0)
        elif now >= job.deadline:
            budget = min(budget, job.deadline + 4.0)
        if self.stopping and self.close_started is not None:
            budget = min(budget, self.close_started + 2.0)
        return max(budget, now + REMOVAL_MIN_ATTEMPT)

    def _append_diagnostic(self, line: str) -> None:
        with self.lock:
            self.cleanup_diagnostics.append(line)

    def _note_removal_error(self, job: Job, exc: BaseException) -> None:
        name = type(exc).__name__
        if name in job.removal_error_types:
            return
        job.removal_error_types.add(name)
        self._append_diagnostic(_oserror_line(exc))

    async def _execute(self, job: Job) -> None:
        outcome = error_result("semgrep.engine_unavailable")
        retain = False
        diagnostic: str | None = None

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
                    version = await run_owned_process(
                        [self.settings.engine, "-version"],
                        job.root,
                        job.deadline,
                        job.cancelled,
                        self.executor,
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
            diagnostic = "kind=native outcome=unfinished"
        except CleanupFailure as exc:
            job.failure = exc
            retain = True
            outcome = exc.outcome or error_result("semgrep.cleanup_failed")
            diagnostic = _native_line(exc)
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
            if job.root is not None and not retain:
                try:
                    await remove_root(
                        job.root,
                        self.executor,
                        self._removal_deadline(job, time.monotonic()),
                        result_for(job.selection or Selection(), error="semgrep.cleanup_failed"),
                    )
                    job.root = None
                except CpuCleanupFailure as exc:
                    job.cpu_failure = exc
                    retain = True
                    outcome = exc.outcome
                    diagnostic = (
                        "kind=root_removal type=none errno=none winerror=none outcome=unfinished"
                    )
                except OSError as exc:
                    retain = True
                    outcome = error_result("semgrep.cleanup_failed")
                    diagnostic = _oserror_line(exc.__cause__)
            # Read the per-process cap before taking runtime.lock: its own lock is
            # never held together with runtime.lock. Only this loop thread changes
            # the count, so the value cannot move before the task is created below.
            allowed = retain and _recovery_allowed()
            with self.lock:
                if retain:
                    self.failed = True
                    self.availability_error = "semgrep.cleanup_failed"
                    self.retained.add(job)
                    if diagnostic is not None:
                        self.cleanup_diagnostics.append(diagnostic)
                    running = self.recovery is not None and not self.recovery.done()
                    if allowed and not running and not self.recovery_expired:
                        # Start the window before the caller can see the failure, so
                        # an observer of cleanup_failed always finds recovery running.
                        self.recovery = self.loop.create_task(self._recover(time.monotonic()))
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

    def _release_retained(self, job: Job) -> None:
        with self.lock:
            self.retained.discard(job)
            self.active.discard(job)

    def _worker_settled(self, job: Job) -> bool:
        failure = job.cpu_failure
        if failure is None:
            return True
        future = failure.future
        if not future.done():
            return False
        exc = future.exception()
        if isinstance(exc, CleanupFailure):
            job.failure = exc
            # The retention line said "unfinished"; record what the worker found.
            self._append_diagnostic(_native_line(exc))
            return True
        if exc is None or isinstance(exc, OSError):
            return True
        job.unconfirmable = True
        return False

    def _native_settled(self, job: Job) -> bool:
        if job.native_settled or job.failure is None:
            job.native_settled = True
            return True
        child = job.failure.child
        if not child.cleaned():
            return False
        if not _tracked_clear(job.failure.tracked):
            return False
        child.close()
        job.native_settled = True
        return True

    async def _root_settled(self, job: Job, window_end: float) -> bool:
        if job.root is None:
            return True
        if not job.root.exists():
            job.root = None
            job.removal = None
            return True
        if job.removal is None:
            job.removal = self.executor.submit(roots.remove_owned_root, job.root)
            job.removal_wait = None
        if job.removal_wait is None:
            # One wrapper per attempt, kept across ticks. The executor future can
            # finish before its completion reaches this wrapper, so only the
            # wrapper's own state decides whether its result can be read.
            job.removal_wait = asyncio.wrap_future(job.removal)
        waiting = job.removal_wait
        timeout = min(1.0, max(0.0, window_end - time.monotonic()))
        await asyncio.wait({waiting}, timeout=timeout)
        if not waiting.done():
            return False
        job.removal = None
        job.removal_wait = None
        try:
            # The wrapper, not the executor future: otherwise its exception is
            # reported as never retrieved when the attempt failed.
            waiting.result()
        except FileNotFoundError as exc:
            if job.root is not None and not job.root.exists():
                job.root = None
                return True
            self._note_removal_error(job, exc)
            return False
        except OSError as exc:
            self._note_removal_error(job, exc)
            return False
        job.root = None
        return True

    async def _recover_job(self, job: Job, window_end: float) -> None:
        if job.unconfirmable:
            return
        try:
            if not self._worker_settled(job) or job.unconfirmable:
                return
            if not self._native_settled(job):
                return
            if await self._root_settled(job, window_end):
                self._release_retained(job)
        except Exception as exc:
            job.unconfirmable = True
            if "check_error" not in job.removal_error_types:
                job.removal_error_types.add("check_error")
                self._append_diagnostic(
                    f"kind=recovery outcome=check_error type={type(exc).__name__}"
                )

    def _note_recovered(self) -> None:
        global _RECOVERIES
        with _RECOVERIES_LOCK:
            _RECOVERIES += 1
        self._append_diagnostic("kind=recovery outcome=recovered")
        with self.lock:
            self.failed = False
            if self.leases and not self.stopping:
                self.availability_error = "semgrep.probe_pending"
                queued = len(self.active) + sum(map(len, self.pending.values()))
                if queued >= 12:
                    if self.retry is not None:
                        self.retry.cancel()
                    self.retry = self.loop.call_later(1, self._retry_probe)
                else:
                    self._enqueue_probe()
            self._pump()
            if self.stopping:
                self._stop_if_empty()

    async def _recover(self, started: float) -> None:
        try:
            await self._recover_window(started)
        except Exception:
            self.recovery_expired = True
            self._append_diagnostic("kind=recovery outcome=task_error")

    async def _recover_window(self, started: float) -> None:
        window_end = started + RECOVERY_WINDOW
        while True:
            if time.monotonic() >= window_end:
                self.recovery_expired = True
                self._append_diagnostic("kind=recovery outcome=expired")
                return
            with self.lock:
                jobs = tuple(self.retained)
            if not jobs:
                self._note_recovered()
                return
            for job in jobs:
                await self._recover_job(job, window_end)
            with self.lock:
                still_retained = bool(self.retained)
            if not still_retained:
                self._note_recovered()
                return
            remaining = window_end - time.monotonic()
            if remaining <= 0:
                continue
            await asyncio.sleep(min(_RECOVERY_POLL, remaining))

    def _diagnostic_snapshot(self) -> tuple[str, ...]:
        with self.lock:
            return tuple(self.cleanup_diagnostics)

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
            # Schedule the stop exactly once. A later close (another owner, the
            # process close) can race loop teardown; job completion re-checks.
            if not self.leases and not self.stopping:
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
                diagnostics=tuple(
                    line
                    for runtime in runtimes
                    if runtime.failed
                    for line in runtime._diagnostic_snapshot()
                ),
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
        diagnostics=(),
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
                "failed",
                reasons=("control_thread_close",),
                diagnostics=runtime._diagnostic_snapshot(),
                **runtime.residuals(),
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
        diagnostics=runtime._diagnostic_snapshot() if status == "failed" else (),
    )
