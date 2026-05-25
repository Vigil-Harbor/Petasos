from __future__ import annotations

__all__: list[str] = []

try:
    from petasos.scanners.presidio import PresidioScanner, anonymize

    __all__ += ["PresidioScanner", "anonymize"]
except ImportError:
    pass
