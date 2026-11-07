"""Native child lifecycle tests; helpers are not scanner detection evidence."""

import asyncio
import contextlib
import importlib.util
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from petasos.scanners._semgrep_process import child_environment, run_process

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("psutil") is None, reason="process monitor extra required"
)


@pytest.mark.parametrize("leader_exited", [False, True])
@pytest.mark.parametrize("group_state", ["gone", "present", "denied"])
def test_posix_signal_denial_requires_exited_leader_and_absent_group(
    monkeypatch: pytest.MonkeyPatch, leader_exited: bool, group_state: str
) -> None:
    import errno
    import signal
    from types import SimpleNamespace

    from petasos.scanners import _semgrep_process as process

    events: list[str] = []
    child = process._PosixChild.__new__(process._PosixChild)
    child.pid = 2000000000
    child._reaped = False
    child._group_signal_complete = False

    def reap() -> int:
        events.append("reap")
        return 0

    child.process = SimpleNamespace(poll=reap, returncode=0)  # type: ignore[assignment]
    monkeypatch.setattr(process, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(process._PosixChild, "poll", lambda self: 0 if leader_exited else None)

    def killpg(pid: int, sig: int) -> None:
        assert pid == child.pid
        if sig == 9:
            events.append("signal")
            raise PermissionError(errno.EPERM, "synthetic denied group signal")
        assert sig == 0
        events.append("check")
        if group_state == "gone":
            raise ProcessLookupError(errno.ESRCH, "synthetic absent group")
        if group_state == "denied":
            raise PermissionError(errno.EPERM, "synthetic inaccessible group")

    monkeypatch.setattr(os, "killpg", killpg, raising=False)
    if not leader_exited:
        with pytest.raises(PermissionError):
            child.terminate(force=True)
        assert not child._group_signal_complete and not child._reaped
        assert events == ["signal"]
    else:
        child.terminate(force=True)
        assert child.cleaned() is (group_state == "gone")
        assert child._reaped
        assert events == ["signal", "reap", "check"]
        child.terminate(force=True)
        assert events == ["signal", "reap", "check"]  # No signals after PID release.


@pytest.mark.skipif(sys.platform == "win32", reason="native POSIX zombie/group semantics")
async def test_exited_posix_leader_is_reaped_before_group_absence_check(tmp_path: Path) -> None:
    from petasos.scanners._semgrep_process import _PosixChild

    child = _PosixChild([sys.executable, "-c", "pass"], tmp_path)
    try:
        end = time.monotonic() + 5
        while child.poll() is None and time.monotonic() < end:
            await asyncio.sleep(0.005)
        assert child.poll() is not None
        child.terminate(force=True)
        assert child.cleaned()
        assert child.process.returncode == 0
    finally:
        child.terminate(force=True)
        child.process.wait(timeout=2)
        child.close()


def test_child_environment_does_not_forward_credentials_or_pythonpath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("API_KEY", "synthetic-credential")
    monkeypatch.setenv("HTTPS_PROXY", "https://invalid.example")
    monkeypatch.setenv("PYTHONPATH", "untrusted")
    environment = child_environment(tmp_path)
    assert not {"API_KEY", "HTTPS_PROXY", "PYTHONPATH"} & environment.keys()
    assert environment["HOME"] == str(tmp_path)


async def test_pipe_output_and_unicode_path(tmp_path: Path) -> None:
    root = tmp_path / "space é"
    root.mkdir()
    result = await run_process(
        [str(vars(sys)["_base_executable"]), "-c", "print('synthetic-output')"],
        root,
        time.monotonic() + 5,
        threading.Event(),
    )
    assert result.returncode == 0
    assert result.error is None
    assert result.stdout.strip() == b"synthetic-output"


@pytest.mark.parametrize("stream,count", [("stdout", 3 * 1024 * 1024), ("stderr", 70000)])
async def test_stream_overflow_is_terminal_and_owned(
    tmp_path: Path, stream: str, count: int
) -> None:
    result = await run_process(
        [
            str(vars(sys)["_base_executable"]),
            "-c",
            f"import sys,time;sys.{stream}.write('x'*{count});sys.{stream}.flush();time.sleep(10)",
        ],
        tmp_path,
        time.monotonic() + 5,
        threading.Event(),
    )
    assert result.error == "semgrep.output_limit"
    assert len(result.stdout) <= 2 * 1024 * 1024


async def test_cancellation_reaps_descendant_holding_inherited_pipes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import psutil

    from petasos.scanners import _semgrep_process as process_module

    child_type = (
        process_module._WindowsChild if sys.platform == "win32" else process_module._PosixChild
    )
    original_terminate = child_type.terminate
    terminated: list[float] = []

    def record_terminate(child: Any, force: bool = False) -> None:
        if not terminated:
            terminated.append(time.monotonic())
        return original_terminate(child, force)

    monkeypatch.setattr(child_type, "terminate", record_terminate)
    cancelled = threading.Event()
    pid_file = tmp_path / "child.pid"
    # Parent intentionally exits first; descendant keeps both output handles.
    helper = (
        "import subprocess,sys,pathlib; "
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],"
        "creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));"
        "pathlib.Path('child.pid').write_text(str(p.pid));print('ready',flush=True)"
    )
    task = asyncio.create_task(
        run_process(
            [str(vars(sys)["_base_executable"]), "-c", helper],
            tmp_path,
            time.monotonic() + 10,
            cancelled,
        )
    )
    deadline = time.monotonic() + 10
    while not pid_file.exists() and not task.done() and time.monotonic() < deadline:
        await asyncio.sleep(0.005)
    try:
        result = await task
    except process_module.CleanupFailure as exc:
        pytest.fail(f"descendant cleanup exceeded its bound: {exc.state!r}")
    assert result.error is None
    pid = int(pid_file.read_text())
    # Windows can keep an exited PID in the system snapshot briefly. A signaled
    # process handle proves termination; pid_exists alone does not.
    with contextlib.suppress(psutil.NoSuchProcess):
        psutil.Process(pid).wait(timeout=0.2)
    assert terminated
    assert time.monotonic() - terminated[0] < 2.2


async def test_cancel_long_running_child(tmp_path: Path) -> None:
    cancelled = threading.Event()
    task = asyncio.create_task(
        run_process(
            [str(vars(sys)["_base_executable"]), "-c", "import time;time.sleep(30)"],
            tmp_path,
            time.monotonic() + 8,
            cancelled,
        )
    )
    await asyncio.sleep(0.1)
    started = time.monotonic()
    cancelled.set()
    result = await task
    assert result.error == "semgrep.cancelled"
    assert time.monotonic() - started < 2.2


async def test_cleanup_os_error_retains_child_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from petasos.scanners import _semgrep_process as process_module

    class Child:
        pid = 2000000000
        closed = False

        def __init__(self, *args: Any) -> None:
            pass

        def read(self, index: int) -> bytes:
            return b""

        def poll(self) -> int:
            return 0

        def terminate(self, force: bool = False) -> None:
            raise PermissionError("synthetic cleanup denial")

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(process_module, "_WindowsChild", Child)
    monkeypatch.setattr(process_module, "_PosixChild", Child)
    with pytest.raises(process_module.CleanupFailure) as caught:
        await run_process(["unused"], tmp_path, time.monotonic() + 1, threading.Event())
    assert not caught.value.child.closed  # type: ignore[union-attr]


def test_posix_leader_is_reaped_only_after_last_group_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os
    import signal
    from types import SimpleNamespace

    import psutil

    from petasos.scanners import _semgrep_process as module

    events: list[str] = []

    def reap() -> int:
        events.append("reap")
        return 0

    def signal_group(pid: int, sig: int) -> None:
        if sig == 0:
            raise ProcessLookupError
        events.append("signal")

    child = object.__new__(module._PosixChild)
    child.pid = 12345
    child._reaped = False
    child._group_signal_complete = False
    child.process = SimpleNamespace(poll=reap, returncode=0)  # type: ignore[assignment]
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "darwin")
        patch.setattr(signal, "SIGKILL", 9, raising=False)
        patch.setattr(os, "killpg", signal_group, raising=False)
        patch.setattr(
            psutil, "Process", lambda pid: SimpleNamespace(status=lambda: psutil.STATUS_ZOMBIE)
        )
        assert child.poll() == 0
        assert not events
        child.terminate(force=True)
        assert child.cleaned()
        child.terminate(force=True)
        assert events == ["signal", "reap"]


async def test_slow_native_spawn_does_not_block_control_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from petasos.scanners import _semgrep_process as process
    from petasos.scanners._semgrep_engine import run_owned_process

    child_type = process._WindowsChild if sys.platform == "win32" else process._PosixChild
    original = child_type.__init__
    entered = threading.Event()
    release = threading.Event()

    def delayed(child: Any, *args: Any) -> None:
        entered.set()
        if not release.wait(3):
            raise RuntimeError("test failed to release native constructor")
        original(child, *args)

    monkeypatch.setattr(child_type, "__init__", delayed)
    cancelled = threading.Event()
    with ThreadPoolExecutor(max_workers=2) as executor:
        task = asyncio.create_task(
            run_owned_process(
                [str(vars(sys)["_base_executable"]), "-c", "import time;time.sleep(30)"],
                tmp_path,
                time.monotonic() + 8,
                cancelled,
                executor,
            )
        )
        try:
            until = time.monotonic() + 1
            while not entered.is_set() and time.monotonic() < until:
                await asyncio.sleep(0.005)
            assert entered.is_set()
            # This coroutine can cancel and release a constructor which is
            # blocked on a worker. Inline spawning cannot reach this point.
            cancelled.set()
        finally:
            release.set()
        result = await task
        assert result.error == "semgrep.cancelled"


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows job membership")
async def test_detached_child_has_no_console_host(tmp_path: Path) -> None:
    from petasos.scanners._semgrep_process import _WindowsChild

    child = _WindowsChild(
        [str(vars(sys)["_base_executable"]), "-c", "import time;time.sleep(30)"],
        tmp_path,
    )
    try:
        await asyncio.sleep(0.3)
        child._capture_descendants()
        assert (
            child.image_names()[child.pid].lower()
            == Path(vars(sys)["_base_executable"]).name.lower()
        )
        # No helper descendants are created, so any member other than the
        # leader would be an unexpected runtime/console process.
        assert not child._descendants
    finally:
        child.terminate(force=True)
        end = time.monotonic() + 2
        while not child.cleaned() and time.monotonic() < end:
            await asyncio.sleep(0.005)
        assert child.cleaned()
        child.close()
