"""Skip the Hermes host tests unless a sandbox was prepared."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

requires_hermes_sandbox = pytest.mark.skipif(
    not os.environ.get("PETASOS_HERMES_SANDBOX"),
    reason="PETASOS_HERMES_SANDBOX is not set to a prepared Hermes sandbox",
)


def _sandbox_version() -> tuple[int, int, int] | None:
    """The Hermes release the sandbox was prepared at, from its manifest."""
    root = os.environ.get("PETASOS_HERMES_SANDBOX")
    if not root:
        return None
    try:
        tag = json.loads((Path(root) / "sandbox-manifest.json").read_text(encoding="utf-8"))["tag"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", str(tag))
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def requires_hermes_at_least(version: tuple[int, int, int]) -> pytest.MarkDecorator:
    """Skip when the sandbox runs an older Hermes; an unreadable tag still runs."""
    found = _sandbox_version()
    return pytest.mark.skipif(
        found is not None and found < version,
        reason=f"needs Hermes v{'.'.join(map(str, version))} behaviour; sandbox has v"
        + ".".join(map(str, found or ())),
    )
