"""Owned local engine children. Submitted text is never executable input."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import ctypes
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import threading

    from petasos._types import ScanResult

STDOUT_LIMIT = 2 * 1024 * 1024
STDERR_LIMIT = 64 * 1024
RSS_LIMIT = 768 * 1024 * 1024

# The runtime installs a per-job observer. Context-local rather than global so
# two concurrently active children cannot overwrite each other's ownership.
CHILD_OBSERVER: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "semgrep_child_observer", default=None
)


CLEANUP_DEADLINE_OBSERVER: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "semgrep_cleanup_deadline", default=None
)


@dataclass(frozen=True)
class ProcessResult:
    returncode: int | None
    stdout: bytes
    error: str | None
    peak_rss: int = 0


def child_environment(root: Path) -> dict[str, str]:
    """Do not forward credentials, proxy settings or Python search paths."""
    env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR") if key in os.environ}
    if os.name == "nt":
        env["PATH"] = str(Path(env.get("SYSTEMROOT", r"C:\Windows")) / "System32")
    else:
        env["PATH"] = "/usr/bin:/bin"
    env.update(
        {
            "HOME": str(root),
            "USERPROFILE": str(root),
            "TEMP": str(root),
            "TMP": str(root),
            "TMPDIR": str(root),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "SEMGREP_SEND_METRICS": "off",
        }
    )
    return env


class _PosixChild:
    def __init__(self, argv: list[str], root: Path) -> None:
        self.process = subprocess.Popen(
            argv,
            cwd=root,
            env=child_environment(root),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            close_fds=True,
        )
        self.pid = self.process.pid
        self._reaped = False
        self._group_killed = False
        assert self.process.stdout is not None and self.process.stderr is not None
        self.streams = (self.process.stdout, self.process.stderr)
        for stream in self.streams:
            if sys.platform != "win32":
                os.set_blocking(stream.fileno(), False)

    def read(self, index: int) -> bytes:
        try:
            return os.read(self.streams[index].fileno(), 65536)
        except BlockingIOError:
            return b""

    def poll(self) -> int | None:
        if self._reaped:
            return self.process.returncode
        import psutil

        # Observe exit without waitpid/Popen.poll reaping the leader. Its zombie
        # retains the PID/PGID until the last process-group signal is delivered.
        try:
            return 0 if psutil.Process(self.pid).status() == psutil.STATUS_ZOMBIE else None
        except psutil.ZombieProcess:
            return 0  # Some psutil platforms signal the same state by exception.
        except psutil.NoSuchProcess:
            # An external reaper destroyed our ownership proof. Never signal a
            # potentially reused group; retain the failed cleanup for reporting.
            self._reaped = True
            raise CleanupFailure(self) from None

    def terminate(self, force: bool = False) -> None:
        with contextlib.suppress(ProcessLookupError):
            if sys.platform != "win32" and not self._reaped:
                os.killpg(self.pid, signal.SIGKILL if force else signal.SIGTERM)
                self._group_killed |= force

    def close(self) -> None:
        for stream in self.streams:
            stream.close()

    def cleaned(self) -> bool:
        if self.poll() is None:
            return False
        if sys.platform == "win32":
            return True  # This implementation is used only on POSIX.
        if not self._group_killed:
            return False
        if not self._reaped:
            if self.process.poll() is None:
                return False
            self._reaped = True
        try:
            os.killpg(self.pid, 0)
        except ProcessLookupError:
            return True
        return False


def _windows_kernel32() -> Any:
    if sys.platform == "win32":
        return ctypes.WinDLL("kernel32", use_last_error=True)
    raise OSError("semgrep.unsupported_platform")


def _windows_last_error() -> int:
    if sys.platform == "win32":
        return ctypes.get_last_error()
    raise OSError("semgrep.unsupported_platform")


class _WindowsChild:
    """Retain the primary thread until job assignment, then resume it.

    Pipes are polled on the runtime loop; no reader can remain blocked on an
    inherited pipe after the child exits. Imports are lazy for base installs.
    """

    def __init__(self, argv: list[str], root: Path) -> None:
        from ctypes import wintypes as w

        k = _windows_kernel32()
        self.k = k
        size = ctypes.c_size_t

        class Security(ctypes.Structure):
            _fields_ = [("length", w.DWORD), ("descriptor", w.LPVOID), ("inherit", w.BOOL)]

        class Startup(ctypes.Structure):
            _fields_ = [
                ("cb", w.DWORD),
                ("reserved", w.LPWSTR),
                ("desktop", w.LPWSTR),
                ("title", w.LPWSTR),
                ("x", w.DWORD),
                ("y", w.DWORD),
                ("cx", w.DWORD),
                ("cy", w.DWORD),
                ("charsx", w.DWORD),
                ("charsy", w.DWORD),
                ("fill", w.DWORD),
                ("flags", w.DWORD),
                ("show", w.WORD),
                ("reserved2size", w.WORD),
                ("reserved2", w.LPBYTE),
                ("stdin", w.HANDLE),
                ("stdout", w.HANDLE),
                ("stderr", w.HANDLE),
            ]

        class StartupEx(ctypes.Structure):
            _fields_ = [("startup", Startup), ("attributes", w.LPVOID)]

        class ProcessInfo(ctypes.Structure):
            _fields_ = [
                ("process", w.HANDLE),
                ("thread", w.HANDLE),
                ("pid", w.DWORD),
                ("tid", w.DWORD),
            ]

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_int64),
                ("job_time", ctypes.c_int64),
                ("flags", w.DWORD),
                ("min_ws", size),
                ("max_ws", size),
                ("active", w.DWORD),
                ("affinity", size),
                ("priority", w.DWORD),
                ("scheduling", w.DWORD),
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("basic", BasicLimits),
                ("io", ctypes.c_uint64 * 6),
                ("process_memory", size),
                ("job_memory", size),
                ("peak_process", size),
                ("peak_job", size),
            ]

        signatures: dict[str, tuple[Any, list[Any]]] = {
            "CreateJobObjectW": (w.HANDLE, [w.LPVOID, w.LPCWSTR]),
            "SetInformationJobObject": (w.BOOL, [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD]),
            "AssignProcessToJobObject": (w.BOOL, [w.HANDLE, w.HANDLE]),
            "TerminateJobObject": (w.BOOL, [w.HANDLE, w.UINT]),
            "QueryInformationJobObject": (
                w.BOOL,
                [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, w.LPVOID],
            ),
            "CreatePipe": (
                w.BOOL,
                [ctypes.POINTER(w.HANDLE), ctypes.POINTER(w.HANDLE), w.LPVOID, w.DWORD],
            ),
            "SetHandleInformation": (w.BOOL, [w.HANDLE, w.DWORD, w.DWORD]),
            "InitializeProcThreadAttributeList": (
                w.BOOL,
                [w.LPVOID, w.DWORD, w.DWORD, ctypes.POINTER(size)],
            ),
            "UpdateProcThreadAttribute": (
                w.BOOL,
                [w.LPVOID, w.DWORD, size, w.LPVOID, size, w.LPVOID, w.LPVOID],
            ),
            "DeleteProcThreadAttributeList": (None, [w.LPVOID]),
            "CreateProcessW": (
                w.BOOL,
                [
                    w.LPCWSTR,
                    w.LPWSTR,
                    w.LPVOID,
                    w.LPVOID,
                    w.BOOL,
                    w.DWORD,
                    w.LPVOID,
                    w.LPCWSTR,
                    w.LPVOID,
                    w.LPVOID,
                ],
            ),
            "ResumeThread": (w.DWORD, [w.HANDLE]),
            "TerminateProcess": (w.BOOL, [w.HANDLE, w.UINT]),
            "WaitForSingleObject": (w.DWORD, [w.HANDLE, w.DWORD]),
            "CloseHandle": (w.BOOL, [w.HANDLE]),
            "GetExitCodeProcess": (w.BOOL, [w.HANDLE, ctypes.POINTER(w.DWORD)]),
            "OpenProcess": (w.HANDLE, [w.DWORD, w.BOOL, w.DWORD]),
            "QueryFullProcessImageNameW": (
                w.BOOL,
                [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)],
            ),
            "PeekNamedPipe": (
                w.BOOL,
                [w.HANDLE, w.LPVOID, w.DWORD, w.LPVOID, ctypes.POINTER(w.DWORD), w.LPVOID],
            ),
            "ReadFile": (w.BOOL, [w.HANDLE, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID]),
        }
        for name, (restype, argtypes) in signatures.items():
            fn = getattr(k, name)
            fn.restype, fn.argtypes = restype, argtypes
        self._handles: list[Any] = []
        self._reads: list[Any] = []
        self._process: Any = None
        self._job: Any = None
        self._descendants: dict[int, Any] = {}
        pi = ProcessInfo()
        attributes: Any = None
        attributes_ready = False
        writes: list[Any] = []
        try:
            self._job = k.CreateJobObjectW(None, None)
            self._check(self._job)
            self._handles.append(self._job)
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000 | 0x100 | 0x200  # kill-on-close, process/job memory
            limits.process_memory = limits.job_memory = 1024 * 1024 * 1024
            self._check(
                k.SetInformationJobObject(
                    self._job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
                )
            )
            sa = Security(ctypes.sizeof(Security), None, True)
            # Separate stdin pipe, closed by the parent after spawn => EOF.
            for index in range(3):
                read, write = w.HANDLE(), w.HANDLE()
                self._check(
                    k.CreatePipe(ctypes.byref(read), ctypes.byref(write), ctypes.byref(sa), 0)
                )
                self._handles.extend((read, write))
                if index == 0:
                    stdin = read
                    self._check(k.SetHandleInformation(write, 1, 0))
                else:
                    self._check(k.SetHandleInformation(read, 1, 0))
                    self._reads.append(read)
                    writes.append(write)
            attribute_size = size()
            k.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(attribute_size))
            attributes = ctypes.create_string_buffer(attribute_size.value)
            self._check(
                k.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(attribute_size))
            )
            attributes_ready = True
            inherited = (w.HANDLE * 3)(stdin, *writes)
            self._check(
                k.UpdateProcThreadAttribute(
                    attributes, 0, 0x20002, inherited, ctypes.sizeof(inherited), None, None
                )
            )
            si = StartupEx()
            si.startup.cb = ctypes.sizeof(si)
            si.startup.flags = 0x100  # STARTF_USESTDHANDLES
            si.startup.stdin, si.startup.stdout, si.startup.stderr = stdin, writes[0], writes[1]
            si.attributes = ctypes.cast(attributes, w.LPVOID)
            env = ctypes.create_unicode_buffer(
                "\0".join(
                    f"{key}={value}" for key, value in sorted(child_environment(root).items())
                )
                + "\0\0"
            )
            cmd = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
            self._check(
                k.CreateProcessW(
                    argv[0],
                    cmd,
                    None,
                    None,
                    True,
                    # DETACHED_PROCESS: explicit stdio pipes need no console
                    # host. Containment still precedes ResumeThread as above.
                    0x80000 | 0x400 | 0x4 | 0x8,
                    env,
                    str(root),
                    ctypes.byref(si),
                    ctypes.byref(pi),
                )
            )
            self._process = pi.process
            self._handles.extend((pi.process, pi.thread))
            self.pid = int(pi.pid)
            self._check(k.AssignProcessToJobObject(self._job, pi.process))
            if k.ResumeThread(pi.thread) == 0xFFFFFFFF:
                self._check(False)
            # Child owns only its explicit stdin/read and stdout+stderr/write.
            keep = [self._job, pi.process, *self._reads]
            for handle in self._handles:
                if handle not in keep:
                    k.CloseHandle(handle)
            self._handles = keep
        except BaseException:
            if pi.process:
                k.TerminateProcess(pi.process, 255)
                if k.WaitForSingleObject(pi.process, 2000) != 0:
                    raise CleanupFailure(self) from None
            self.close()
            raise
        finally:
            if attributes_ready:
                k.DeleteProcThreadAttributeList(attributes)

    @staticmethod
    def _check(ok: Any) -> None:
        if not ok:
            raise OSError("semgrep.process_api_failure")

    def read(self, index: int) -> bytes:
        from ctypes import wintypes as w

        available = w.DWORD()
        if not self.k.PeekNamedPipe(
            self._reads[index], None, 0, None, ctypes.byref(available), None
        ):
            if _windows_last_error() in (109, 233):
                return b""
            self._check(False)
        if not available.value:
            return b""
        buf = ctypes.create_string_buffer(min(65536, available.value))
        size = w.DWORD()
        self._check(self.k.ReadFile(self._reads[index], buf, len(buf), ctypes.byref(size), None))
        return buf.raw[: size.value]

    def poll(self) -> int | None:
        from ctypes import wintypes as w

        if self.k.WaitForSingleObject(self._process, 0) == 258:
            return None
        code = w.DWORD()
        self._check(self.k.GetExitCodeProcess(self._process, ctypes.byref(code)))
        return int(code.value)

    def _capture_descendants(self) -> None:
        from ctypes import wintypes as w

        class ProcessIds(ctypes.Structure):
            _fields_ = [
                ("assigned", w.DWORD),
                ("count", w.DWORD),
                ("ids", ctypes.c_size_t * 256),
            ]

        ids = ProcessIds()
        if not self.k.QueryInformationJobObject(
            self._job, 3, ctypes.byref(ids), ctypes.sizeof(ids), None
        ):
            # Kill even when the bounded membership snapshot overflows. The
            # caller must retain ownership because it cannot prove complete reap.
            self.k.TerminateJobObject(self._job, 255)
            raise CleanupFailure(self)
        for pid in ids.ids[: ids.count]:
            if pid == self.pid or pid in self._descendants:
                continue
            handle = self.k.OpenProcess(0x101000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED
            if not handle:
                # Optional diagnostics must not weaken termination ownership.
                handle = self.k.OpenProcess(0x100000, False, pid)
            if handle:
                self._descendants[pid] = handle
                self._handles.append(handle)
            elif _windows_last_error() != 87:  # already-exited PID
                self.k.TerminateJobObject(self._job, 255)
                raise CleanupFailure(self)

    def terminate(self, force: bool = False) -> None:
        self._capture_descendants()
        self._check(self.k.TerminateJobObject(self._job, 255))

    def cleaned(self) -> bool:
        from ctypes import wintypes as w

        class Accounting(ctypes.Structure):
            _fields_ = [
                ("times", ctypes.c_int64 * 4),
                ("faults", w.DWORD),
                ("total", w.DWORD),
                ("active", w.DWORD),
                ("terminated", w.DWORD),
            ]

        accounting = Accounting()
        self._check(
            self.k.QueryInformationJobObject(
                self._job, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None
            )
        )
        leader_signalled = self.poll() is not None
        descendants = {
            pid: int(self.k.WaitForSingleObject(handle, 0))
            for pid, handle in self._descendants.items()
        }
        # Bounded, source-free evidence for a retained cleanup failure. Preserve
        # the actual handle state, rather than rediscovering possibly reused PIDs.
        self._last_cleanup_state = {
            "leader_signalled": leader_signalled,
            "total": int(accounting.total),
            "active": int(accounting.active),
            "terminated": int(accounting.terminated),
            "descendant_waits": descendants,
        }
        return (
            leader_signalled
            and accounting.active == 0
            and all(status == 0 for status in descendants.values())
        )

    def image_names(self) -> dict[int, str]:
        """Failure-only diagnostics from owned handles, without source or paths."""
        from ctypes import wintypes as w

        names = {}
        for pid, handle in {self.pid: self._process, **self._descendants}.items():
            buffer = ctypes.create_unicode_buffer(32768)
            size = w.DWORD(len(buffer))
            if self.k.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                names[pid] = buffer.value.rsplit("\\", 1)[-1]
            else:
                names[pid] = "unavailable"
        return names

    def close(self) -> None:
        for handle in reversed(self._handles):
            self.k.CloseHandle(handle)
        self._handles.clear()


class CleanupFailure(RuntimeError):
    """The caller must retain its capacity/root after unsuccessful cleanup."""

    def __init__(self, child: _WindowsChild | _PosixChild) -> None:
        super().__init__("semgrep.cleanup_failed")
        self.child = child
        self.state = getattr(child, "_last_cleanup_state", None)
        if self.state is not None and isinstance(child, _WindowsChild):
            with contextlib.suppress(Exception):
                self.state = {**self.state, "images": child.image_names()}
        self.outcome: ScanResult | None = None


async def run_process(
    argv: list[str],
    root: Path,
    deadline: float,
    cancelled: threading.Event,
) -> ProcessResult:
    """Bound streams/RSS/deadline and reap before returning, including cancellation."""
    import psutil  # optional extra; never imported on the base path

    child = _WindowsChild(argv, root) if sys.platform == "win32" else _PosixChild(argv, root)
    tracked: dict[tuple[int, float], Any] = {}
    proc: Any = None
    stdout = bytearray()
    stderr_size = 0
    peak = 0
    error: str | None = None
    sample_at = 0.0
    code: int | None = None
    cleanup_started: float | None = None
    try:
        observer = CHILD_OBSERVER.get()
        if observer is not None:
            observer(child)
        with contextlib.suppress(psutil.NoSuchProcess):
            proc = psutil.Process(child.pid)
        while True:
            now = time.monotonic()
            if cancelled.is_set() and error is None:
                error = "semgrep.cancelled"
            if now >= deadline and error is None:
                error = "ScannerTimeout: semgrep.deadline"
            if now >= sample_at and proc is not None:
                sample_at = now + 0.1
                try:
                    peak = max(peak, proc.memory_info().rss)
                    # Windows Job Objects contain descendants before execution
                    # and report their active count. A system-wide PID snapshot
                    # is slower and can retain stale process-table entries.
                    if sys.platform != "win32":
                        for descendant in proc.children(recursive=True):
                            tracked[(descendant.pid, descendant.create_time())] = descendant
                    if peak > RSS_LIMIT and error is None:
                        error = "semgrep.memory_limit"
                except psutil.NoSuchProcess:
                    pass
            for i in (0, 1):
                chunk = child.read(i)
                if i == 0:
                    if len(stdout) + len(chunk) > STDOUT_LIMIT:
                        error = "semgrep.output_limit"
                    elif error != "semgrep.output_limit":
                        stdout.extend(chunk)
                else:
                    stderr_size += len(chunk)
                    if stderr_size > STDERR_LIMIT:
                        error = "semgrep.output_limit"
            if error is not None and cleanup_started is None:
                cleanup_started = now
                cleanup_observer = CLEANUP_DEADLINE_OBSERVER.get()
                if cleanup_observer is not None:
                    cleanup_observer(cleanup_started + 2)
                child.terminate()
            if cleanup_started is not None and now - cleanup_started >= 0.25:
                child.terminate(force=True)
            code = child.poll()
            if code is not None:
                # Drain buffered output, bounded by the same byte cap.
                while chunk := child.read(0):
                    if len(stdout) + len(chunk) > STDOUT_LIMIT:
                        error = "semgrep.output_limit"
                        break
                    stdout.extend(chunk)
                while chunk := child.read(1):
                    stderr_size += len(chunk)
                    if stderr_size > STDERR_LIMIT:
                        error = "semgrep.output_limit"
                        break
                break
            if cleanup_started is not None and now - cleanup_started >= 2:
                raise CleanupFailure(child)
            await asyncio.sleep(0.005)
    finally:
        # This also handles unexpected errors and task cancellation. The runtime
        # cancels via Event, not Task.cancel, so cleanup owns its entire allowance.
        end = (cleanup_started if cleanup_started is not None else time.monotonic()) + 2
        cleanup_observer = CLEANUP_DEADLINE_OBSERVER.get()
        if cleanup_observer is not None:
            cleanup_observer(end)
        try:
            child.terminate(force=True)
            for (_pid, born), descendant in tracked.items():
                try:
                    if descendant.is_running() and descendant.create_time() == born:
                        descendant.kill()
                except psutil.NoSuchProcess:
                    pass
            while not child.cleaned() and time.monotonic() < end:
                await asyncio.sleep(0.005)
            if not child.cleaned():
                raise CleanupFailure(child)
            # Do not block the manager loop in psutil.wait: a sibling's cancel
            # request and its two-second cleanup budget must keep advancing.
            while tracked:
                for identity, descendant in tuple(tracked.items()):
                    try:
                        alive = descendant.is_running() and descendant.create_time() == identity[1]
                        if not alive or descendant.status() == psutil.STATUS_ZOMBIE:
                            del tracked[identity]
                    except psutil.NoSuchProcess:
                        del tracked[identity]
                if not tracked:
                    break
                if time.monotonic() >= end:
                    raise CleanupFailure(child)
                await asyncio.sleep(0.005)
            code = child.poll()
            child.close()
        except CleanupFailure:
            raise
        except BaseException as exc:
            # Even an access error or repeated cancellation cannot turn an
            # unreaped native child into a released scheduler slot.
            raise CleanupFailure(child) from exc
        observer = CHILD_OBSERVER.get()
        if observer is not None:
            observer(None)
    return ProcessResult(code, bytes(stdout), error, peak)
