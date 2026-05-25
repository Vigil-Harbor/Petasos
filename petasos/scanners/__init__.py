from __future__ import annotations

from petasos.scanners.minimal import MinimalScanner

__all__ = ["MinimalScanner"]

try:
    from petasos.scanners.llm_guard import LlmGuardScanner  # noqa: F401

    __all__.append("LlmGuardScanner")
except ImportError as _exc:
    if "llm_guard" not in str(_exc):
        raise
    del _exc
