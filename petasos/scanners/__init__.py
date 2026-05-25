from petasos.scanners.minimal import MinimalScanner

__all__ = ["MinimalScanner"]

try:
    from petasos.scanners.llama_firewall import LlamaFirewallScanner  # noqa: F401

    __all__.append("LlamaFirewallScanner")
except ImportError:
    pass
