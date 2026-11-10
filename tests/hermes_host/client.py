"""Call the sandbox harness. This module never imports Hermes."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

HARNESS = Path(__file__).resolve().parent / "harness.py"


def sandbox_path() -> Path:
    raw = os.environ.get("PETASOS_HERMES_SANDBOX", "")
    if not raw:
        raise RuntimeError("PETASOS_HERMES_SANDBOX is not set")
    return Path(raw).resolve()


def invoke(sandbox: Path, request: dict[str, Any], *, timeout: float = 180) -> dict[str, Any]:
    """Run one harness action inside the sandbox wrapper and return its JSON object."""
    wrapper = sandbox / "bin" / "with-sandbox"
    python = sandbox / "venv" / "bin" / "python"
    completed = subprocess.run(
        [str(wrapper), str(python), str(HARNESS)],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
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
