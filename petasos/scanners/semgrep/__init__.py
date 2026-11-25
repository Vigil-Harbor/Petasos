"""Opt-in Semgrep scanning with explicit lifecycle ownership."""

from __future__ import annotations

from petasos.scanners.semgrep.adapter import SemgrepLifecycleOwner, SemgrepScanner
from petasos.scanners.semgrep.runtime import (
    SemgrepCleanupError,
    SemgrepCloseResult,
    close_semgrep_runtime,
)

__all__ = [
    "SemgrepCleanupError",
    "SemgrepCloseResult",
    "SemgrepLifecycleOwner",
    "SemgrepScanner",
    "close_semgrep_runtime",
]
