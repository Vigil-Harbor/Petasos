"""Call the sandbox harness. This module never imports Hermes."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

HARNESS = Path(__file__).resolve().parent / "harness.py"
PETASOS_HARNESS = Path(__file__).resolve().parent / "petasos_harness.py"
_HOME_ENV = "PETASOS_HERMES_HOME"
_PID_FILE = "host-test-pids"


@dataclass(frozen=True)
class Sandbox:
    """One prepared sandbox and the Hermes home a test is using."""

    root: Path
    home: Path


def sandbox_path() -> Path:
    """Provide sandbox path for the test fixture."""
    raw = os.environ.get("PETASOS_HERMES_SANDBOX", "")
    if not raw:
        raise RuntimeError("PETASOS_HERMES_SANDBOX is not set")
    return Path(raw).resolve()


def fresh_home(sandbox: Path, label: str) -> Path:
    """Create a new Hermes home under ``<sandbox>/homes`` and return it.

    The directory is empty. Hermes keeps its managed environments under the
    home (``installs/``), so a new home is a new environment too.
    """
    root = sandbox.resolve()
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-")[:60] or "home"
    home = (root / "homes" / f"{slug}-{uuid.uuid4().hex[:8]}").resolve()
    if root not in home.parents:
        raise RuntimeError(f"refusing Hermes home outside the sandbox: {home}")
    home.mkdir(parents=True)
    return home


def sandbox_env(home: Path | None) -> dict[str, str]:
    """Environment for a wrapper command. Inherited ``HERMES_*`` is dropped.

    ``home`` must already be inside the sandbox. The wrapper checks again.
    """
    env = {key: value for key, value in os.environ.items() if not key.startswith("HERMES_")}
    env.pop(_HOME_ENV, None)
    if home is not None:
        root = sandbox_path()
        resolved = home.resolve()
        if root not in resolved.parents:
            raise RuntimeError(f"refusing Hermes home outside the sandbox: {resolved}")
        env[_HOME_ENV] = str(resolved)
    return env


def invoke(
    sandbox: Path,
    request: dict[str, Any],
    *,
    home: Path | None = None,
    harness: Path | None = None,
    timeout: float = 180,
) -> dict[str, Any]:
    """Run one harness action inside the sandbox wrapper and return its JSON object."""
    wrapper = sandbox / "bin" / "with-sandbox"
    python = sandbox / "venv" / "bin" / "python"
    script = harness if harness is not None else HARNESS
    completed = subprocess.run(
        [str(wrapper), str(python), str(script)],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env=sandbox_env(home),
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"harness {request.get('action')} exited {completed.returncode}\n"
            f"stdout:\n{completed.stdout[-2000:]}\nstderr:\n{completed.stderr[-4000:]}"
        )
    try:
        return cast("dict[str, Any]", json.loads(completed.stdout))
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"harness returned non-JSON stdout:\n{completed.stdout[-2000:]}"
        ) from exc


def call(
    box: Sandbox,
    request: dict[str, Any],
    *,
    harness: Path | None = None,
    timeout: float = 180,
) -> dict[str, Any]:
    """Run one harness action against ``box.home``."""
    return invoke(box.root, request, home=box.home, harness=harness, timeout=timeout)


def remember_pid(sandbox: Path, pid: int) -> None:
    """Record a process this session started, so a later reap can stop it."""
    path = sandbox / "tmp" / _PID_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{pid}\n")


def _belongs_to_sandbox(pid: int, sandbox: Path) -> bool:
    completed = subprocess.run(
        ["ps", "eww", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    text = completed.stdout
    return str(sandbox) in text or str(sandbox.resolve()) in text


def reap(sandbox: Path) -> list[int]:
    """Stop processes this session recorded, when they still belong to the sandbox.

    Returns pids that were still alive after a kill. An empty list means none
    of the recorded processes are running.
    """
    path = sandbox / "tmp" / _PID_FILE
    if not path.is_file():
        return []
    pids: list[int] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().isdigit():
            pids.append(int(line.strip()))
    for pid in pids:
        if not _belongs_to_sandbox(pid, sandbox):
            continue
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            continue
    still: list[int] = []
    for pid in pids:
        if not _belongs_to_sandbox(pid, sandbox):
            continue
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            continue
        if _belongs_to_sandbox(pid, sandbox):
            still.append(pid)
    if not still:
        path.unlink(missing_ok=True)
    return still
