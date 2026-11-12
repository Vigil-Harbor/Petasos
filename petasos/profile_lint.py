"""Identify loopback inference endpoints without accepting hostname lookalikes.

See docs/architecture/rationale.md, "Local inference endpoint boundaries"."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

# A supplied base URL takes precedence over the local-provider allowlist.
_LOCAL_PROVIDERS = frozenset({"lmstudio", "llama.cpp", "llamacpp", "ollama", "local", "localai"})


def is_local_inference_endpoint(provider: str | None, base_url: str | None) -> bool:
    """True iff the resolved inference endpoint is on the local box.

    Fail-secure: ambiguous or unrecognized inputs return False, because the
    caller uses this as a release-blocker gate ("financial data must not
    egress the box"). The verdict errs toward "not local".
    """
    base = (base_url or "").strip()
    provider_name = (provider or "").strip()

    if not base and not provider_name:
        return False

    if base:
        try:
            host = urlsplit(base).hostname
        except ValueError:
            # Malformed URLs cannot establish local inference.
            return False
        if host is None:
            # A schemeless address has no hostname and cannot establish loopback.
            return False
        # urlsplit removes IPv6 brackets; one terminal dot permits the localhost FQDN.
        if host.endswith("."):
            host = host[:-1]
        try:
            host_ip = ipaddress.ip_address(host)
        except ValueError:
            # See docs/architecture/rationale.md, "Local inference endpoint boundaries".
            return host == "localhost"
        # See docs/architecture/rationale.md, "Local inference endpoint boundaries".
        if isinstance(host_ip, ipaddress.IPv6Address):
            mapped = host_ip.ipv4_mapped
            if mapped is not None:
                return mapped.is_loopback
        return host_ip.is_loopback

    return provider_name.lower() in _LOCAL_PROVIDERS
