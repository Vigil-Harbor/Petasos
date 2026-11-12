"""Start and stop one sandboxed Hermes dashboard on a prepared home.

This module never imports Hermes. The dashboard runs through the sandbox
wrapper, bound to 127.0.0.1 on a free port, in its own process group, so
stopping it signals that group and nothing else. It never uses
``hermes dashboard --stop`` or ``--status``: those scan the process table and
would signal every dashboard on the machine.

    python tests/hermes_host/dashboard_server.py start --sandbox S --home H
    python tests/hermes_host/dashboard_server.py stop --sandbox S --pid P
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

if __name__ == "__main__" and __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import contextlib

from tests.hermes_host.client import remember_pid, sandbox_env

TOKEN = "petasos-dashboard-demo"

_STARTED: dict[int, subprocess.Popen[bytes]] = {}


@dataclass(frozen=True)
class Dashboard:
    """One running dashboard."""

    sandbox: Path
    home: Path
    port: int
    pid: int
    log: Path

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as reply:
            return bool(reply.status == 200)
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def start(sandbox: Path, home: Path, *, timeout: float = 60) -> Dashboard:
    """Start the dashboard for ``home`` and wait until it answers."""
    os.environ["PETASOS_HERMES_SANDBOX"] = str(sandbox)
    port = free_port()
    log = sandbox / "tmp" / f"dashboard-{home.name}-{port}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    command = (
        f"export HERMES_DASHBOARD_SESSION_TOKEN={TOKEN}; "
        "exec hermes dashboard --isolated --host 127.0.0.1 "
        f"--port {port} --no-open --skip-build"
    )
    with log.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(
            [str(sandbox / "bin" / "with-sandbox"), "bash", "-c", command],
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=sandbox_env(home),
        )
    remember_pid(sandbox, process.pid)
    _STARTED[process.pid] = process
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            break
        if _ready(port):
            return Dashboard(sandbox, home, port, process.pid, log)
        time.sleep(0.25)
    stop(process.pid)
    tail = log.read_text(encoding="utf-8")[-3000:]
    raise RuntimeError(f"dashboard did not become ready\n{tail}")


def _group_alive(pgid: int) -> bool:
    """True while any process in the group is running (zombies do not count)."""
    listing = subprocess.run(
        ["ps", "-A", "-o", "pid=,pgid=,stat="],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] == str(pgid) and not parts[2].startswith("Z"):
            return True
    return False


def _signal(pgid: int, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, sig)


def stop(pid: int, *, wait: float = 10) -> bool:
    """Stop the dashboard's process group. True when nothing is left running."""
    process = _STARTED.pop(pid, None)
    _signal(pid, signal.SIGTERM)
    deadline = time.time() + wait
    while time.time() < deadline:
        if process is not None:
            process.poll()
        if not _group_alive(pid):
            return True
        time.sleep(0.2)
    _signal(pid, signal.SIGKILL)
    time.sleep(0.5)
    if process is not None:
        process.poll()
    return not _group_alive(pid)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="action", required=True)
    up = sub.add_parser("start")
    up.add_argument("--sandbox", required=True, type=Path)
    up.add_argument("--home", required=True, type=Path)
    down = sub.add_parser("stop")
    down.add_argument("--sandbox", required=True, type=Path)
    down.add_argument("--pid", required=True, type=int)
    args = parser.parse_args(argv)
    if args.action == "start":
        board = start(args.sandbox.resolve(), args.home.resolve())
        json.dump({"url": board.url, "pid": board.pid, "log": str(board.log)}, sys.stdout)
        sys.stdout.write("\n")
        return 0
    stopped = stop(args.pid)
    json.dump({"stopped": stopped}, sys.stdout)
    sys.stdout.write("\n")
    return 0 if stopped else 1


if __name__ == "__main__":
    raise SystemExit(main())
