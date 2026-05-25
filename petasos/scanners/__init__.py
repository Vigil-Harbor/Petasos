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

try:
    from petasos.scanners.llama_firewall import LlamaFirewallScanner  # noqa: F401

    __all__.append("LlamaFirewallScanner")
except ImportError as _exc:
    if getattr(_exc, "name", None) not in ("llamafirewall", "llama_firewall"):
        raise
    del _exc
