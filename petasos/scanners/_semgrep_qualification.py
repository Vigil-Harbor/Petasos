"""Validate packaged reference measurements without claiming a local benchmark."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import sys
from pathlib import Path

from petasos.scanners._semgrep_engine import ENGINE_VERSION

_MANIFEST = Path(__file__).with_name("semgrep_qualification.json")
_RULES = Path(__file__).with_name("semgrep_rules") / "rules.json"
_WORKLOAD = "eight_outstanding_three_profiles"


def platform_key() -> str:
    machine = platform.machine().lower()
    if sys.platform == "win32" and machine in ("amd64", "x86_64"):
        return "windows_x64"
    if sys.platform == "darwin" and machine == "arm64":
        return "macos_arm64"
    return "unsupported"


def qualification_warning(timeout: float, engine_digest: str | None) -> str | None:
    """Malformed, missing or mismatched evidence uses the unqualified 8s fallback."""
    measured: list[float] = []
    try:
        with _MANIFEST.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("oversize manifest")
        manifest = json.loads(raw)
        if manifest.get("schema_version") != 1:
            raise ValueError("unknown schema")
        rows = manifest["measurements"]
        if not isinstance(rows, list) or len(rows) > 32:
            raise ValueError("invalid measurements")
        rules_digest = hashlib.sha256(_RULES.read_bytes()).hexdigest()
        for row in rows:
            if not isinstance(row, dict):
                continue
            if (
                row.get("platform") != platform_key()
                or row.get("engine_version") != ENGINE_VERSION
                or row.get("engine_sha256") != (engine_digest or "").lower()
                or row.get("rules_sha256") != rules_digest
                or row.get("workload") != _WORKLOAD
                or row.get("qualified") is not True
                or not isinstance(row.get("hardware"), dict)
                or not row["hardware"]
            ):
                continue
            value = row.get("loaded_p95_seconds")
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and 0 < value <= 8
            ):
                measured.append(float(value))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        measured = []
    reference = max(measured) if measured else 8.0
    if timeout >= reference:
        return None
    evidence = "packaged_reference" if measured else "unqualified_fallback"
    return (
        f"deadline_below_qualified_load: workload={_WORKLOAD} "
        f"reference_p95_seconds={reference:.3f} evidence={evidence}"
    )
