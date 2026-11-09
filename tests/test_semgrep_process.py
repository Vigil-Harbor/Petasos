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
async def test_exited_posix_leader_is_reaped_before_group_absence_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    import errno
    import json

    from petasos.scanners._semgrep_process import _PosixChild

    if sys.platform == "win32":
        pytest.skip("native POSIX zombie/group semantics")
    child = _PosixChild([sys.executable, "-c", "pass"], tmp_path)
    original = os.killpg
    events: list[tuple[int, int, bool]] = []

    def observe(pid: int, sig: int) -> None:
        try:
            original(pid, sig)
        except OSError as exc:
            events.append((sig, exc.errno or 0, child._reaped))
            raise
        else:
            events.append((sig, 0, child._reaped))

    monkeypatch.setattr(os, "killpg", observe)
    try:
        end = time.monotonic() + 5
        while child.poll() is None and time.monotonic() < end:
            await asyncio.sleep(0.005)
        assert child.poll() is not None
        child.terminate(force=True)
        end = time.monotonic() + 2
        while not child.cleaned() and time.monotonic() < end:
            await asyncio.sleep(0.005)
        assert child.cleaned()
        assert child.process.returncode == 0
        assert events[0][0] != 0 and not events[0][2]
        assert all(sig == 0 and reaped for sig, _error, reaped in events[1:])
        assert events[-1][1] == errno.ESRCH
    finally:
        record_property("posix_group_signal_results", json.dumps(events))
        child.terminate(force=True)
        child.process.wait(timeout=2)
        child.close()


def _stub_posix_child(monkeypatch: pytest.MonkeyPatch, poll: Any, events: list[str]) -> Any:
    import signal
    from types import SimpleNamespace

    from petasos.scanners import _semgrep_process as process

    child = process._PosixChild.__new__(process._PosixChild)
    child.pid = 2000000001
    child._reaped = False
    child._group_signal_complete = False

    def reap() -> int:
        events.append("reap")
        return 0

    child.process = SimpleNamespace(poll=reap, returncode=0)  # type: ignore[assignment]
    monkeypatch.setattr(process, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(signal, "SIGTERM", 15, raising=False)
    monkeypatch.setattr(process._PosixChild, "poll", poll)
    return child


def test_sigterm_denial_after_exit_does_not_complete_final_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import errno

    events: list[str] = []
    child = _stub_posix_child(monkeypatch, lambda self: 0, events)

    def killpg(pid: int, sig: int) -> None:
        events.append(f"signal:{sig}")
        raise PermissionError(errno.EPERM, "synthetic denied signal")

    monkeypatch.setattr(os, "killpg", killpg, raising=False)
    child.terminate()
    assert not child._group_signal_complete
    assert not child.cleaned()
    assert events == ["signal:15"]  # Never reap before the final-signal phase.


def test_absent_group_signal_still_requires_post_reap_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    child = _stub_posix_child(monkeypatch, lambda self: 0, events)
    present = True

    def killpg(pid: int, sig: int) -> None:
        events.append(f"signal:{sig}")
        if sig or not present:
            raise ProcessLookupError

    monkeypatch.setattr(os, "killpg", killpg, raising=False)
    child.terminate(force=True)
    assert child._group_signal_complete
    assert not child.cleaned()
    child.terminate(force=True)  # No new signal after the PID has been released.
    assert not child.cleaned()
    present = False
    assert child.cleaned()
    assert events == ["signal:9", "reap", "signal:0", "signal:0", "signal:0"]


def test_external_reap_during_signal_denial_retains_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from petasos.scanners import _semgrep_process as process

    events: list[str] = []

    def poll(child: Any) -> None:
        child._reaped = True
        raise process.CleanupFailure(child) from None

    child = _stub_posix_child(monkeypatch, poll, events)

    def killpg(pid: int, sig: int) -> None:
        events.append(f"signal:{sig}")
        raise PermissionError

    monkeypatch.setattr(os, "killpg", killpg, raising=False)
    with pytest.raises(process.CleanupFailure):
        child.terminate(force=True)
    assert not child._group_signal_complete
    child.terminate(force=True)
    assert events == ["signal:9"]


def test_unexpected_group_signal_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    import errno

    events: list[str] = []
    child = _stub_posix_child(monkeypatch, lambda self: 0, events)

    def killpg(pid: int, sig: int) -> None:
        raise OSError(errno.EINVAL, "synthetic invalid signal")

    monkeypatch.setattr(os, "killpg", killpg, raising=False)
    with pytest.raises(OSError) as caught:
        child.terminate(force=True)
    assert caught.value.errno == errno.EINVAL
    assert not child._group_signal_complete and not child._reaped


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


def test_root_recovery_skips_out_of_range_pids_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import subprocess
    import tempfile

    from petasos.scanners._semgrep_roots import recover_roots

    exited = subprocess.Popen([sys.executable, "-c", "pass"])
    exited.wait()
    oversized = 1 << 100
    markers = {
        "psg-oversize": {"pid": oversized, "born": 1.0, "children": []},
        "psg-bigchild": {
            "pid": exited.pid,
            "born": 1.0,
            "children": [{"pid": oversized, "born": 1.0}],
        },
        "psg-stalerot": {"pid": exited.pid, "born": 1.0, "children": []},
    }
    for name, marker in markers.items():
        (tmp_path / name).mkdir()
        (tmp_path / name / "petasos-owner.json").write_text(json.dumps({"schema": 1, **marker}))
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

    assert recover_roots() == 1
    assert not (tmp_path / "psg-stalerot").exists()
    assert (tmp_path / "psg-oversize").exists()
    assert (tmp_path / "psg-bigchild").exists()


def _stale_root(tmp_path: Path, name: str) -> Path:
    import json
    import subprocess

    exited = subprocess.Popen([sys.executable, "-c", "pass"])
    exited.wait()
    root = tmp_path / name
    root.mkdir()
    (root / "petasos-owner.json").write_text(
        json.dumps({"schema": 1, "pid": exited.pid, "born": 1.0, "children": []})
    )
    return root


def test_root_recovery_leaves_another_users_roots_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tempfile

    from petasos.scanners._semgrep_roots import recover_roots

    stale = _stale_root(tmp_path, "psg-foreign0")
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    # A shared temp directory can hold roots created by other accounts. Pretend
    # the current user is someone else; the recorded owner no longer matches.
    monkeypatch.setattr(os, "getuid", lambda: 1 << 20, raising=False)

    assert recover_roots() == 0
    assert stale.exists()


def test_root_recovery_does_not_block_on_a_fifo_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tempfile

    from petasos.scanners._semgrep_roots import recover_roots

    if sys.platform == "win32":
        pytest.skip("FIFO markers need POSIX")
    # A FIFO passes an is_symlink/stat-size check and its open blocks until a
    # writer appears. Recovery must skip it and still remove the stale root.
    trap = tmp_path / "psg-fifotrap"
    trap.mkdir()
    os.mkfifo(trap / "petasos-owner.json")
    stale = _stale_root(tmp_path, "psg-stalerot")
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

    outcome: list[int] = []
    worker = threading.Thread(target=lambda: outcome.append(recover_roots()), daemon=True)
    worker.start()
    worker.join(10.0)
    assert not worker.is_alive(), "recover_roots blocked on the FIFO marker"
    assert outcome == [1]
    assert not stale.exists()
    assert trap.exists()


async def test_descendant_memory_counts_against_the_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from petasos.scanners import _semgrep_process as process

    monkeypatch.setattr(process, "RSS_LIMIT", 96 * 1024 * 1024)
    python = str(vars(sys)["_base_executable"])
    # A small leader waits on a child that holds well over the (lowered) budget.
    helper = "import time;b=bytearray(192*1024*1024);time.sleep(30)"
    leader = f"import subprocess,sys;subprocess.run([sys.executable,'-c',{helper!r}])"
    start = time.monotonic()
    result = await run_process([python, "-c", leader], tmp_path, start + 20, threading.Event())
    assert result.error == "semgrep.memory_limit"
    assert result.peak_rss > 96 * 1024 * 1024
    assert time.monotonic() - start < 15
