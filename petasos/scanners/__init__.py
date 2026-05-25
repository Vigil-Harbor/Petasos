from __future__ import annotations

from petasos.scanners.minimal import MinimalScanner

__all__: list[str] = ["MinimalScanner"]

try:
    from petasos.scanners.llm_guard import LlmGuardScanner  # noqa: F401

    __all__.append("LlmGuardScanner")
except ImportError as _exc:
    _name = getattr(_exc, "name", None) or ""
    if _name.split(".")[0] != "llm_guard":
        raise
    del _exc, _name

try:
    from petasos.scanners.presidio import PresidioScanner, anonymize

    __all__ += ["PresidioScanner", "anonymize"]
except ImportError as exc:
    _name = getattr(exc, "name", None) or ""
    if _name.split(".")[0] not in ("presidio_analyzer", "presidio_anonymizer"):
        raise
    del exc, _name
