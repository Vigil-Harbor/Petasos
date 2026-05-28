from __future__ import annotations

import logging

from petasos.scanners.minimal import MinimalScanner

__all__: list[str] = ["MinimalScanner"]

_logger = logging.getLogger(__name__)


def _is_missing_package(exc: ImportError, expected_names: set[str]) -> bool:
    """Return True only if exc is a top-level 'module not found' for one of
    the expected package names."""
    exc_name = getattr(exc, "name", None)
    if exc_name is None:
        return False
    return exc_name in expected_names


try:
    from petasos.scanners.llm_guard import LlmGuardScanner  # noqa: F401

    __all__.append("LlmGuardScanner")
except ImportError as _exc:
    if not _is_missing_package(_exc, {"llm_guard"}):
        raise
    _logger.debug("LlmGuardScanner not available: %s", _exc)
    del _exc

try:
    from petasos.scanners.llama_firewall import LlamaFirewallScanner  # noqa: F401

    __all__.append("LlamaFirewallScanner")
except ImportError as _exc:
    if not _is_missing_package(_exc, {"llamafirewall", "llama_firewall"}):
        raise
    _logger.debug("LlamaFirewallScanner not available: %s", _exc)
    del _exc

try:
    from petasos.scanners.presidio import PresidioScanner, anonymize

    __all__ += ["PresidioScanner", "anonymize"]
except ImportError as _exc:
    if not _is_missing_package(_exc, {"presidio_analyzer", "presidio_anonymizer"}):
        raise
    _logger.debug("PresidioScanner not available: %s", _exc)
    del _exc
