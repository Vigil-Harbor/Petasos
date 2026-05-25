from __future__ import annotations

__all__: list[str] = []

try:
    from petasos.scanners.presidio import PresidioScanner, anonymize

    __all__ += ["PresidioScanner", "anonymize"]
except ImportError as exc:
    _name = getattr(exc, "name", None) or ""
    if _name.split(".")[0] not in ("presidio_analyzer", "presidio_anonymizer"):
        raise
