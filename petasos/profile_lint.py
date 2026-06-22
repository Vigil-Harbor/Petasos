"""PET-133: a generic, fail-secure local-inference lint predicate (decision D3).

The leak Petasos cannot intercept is the LLM inference call itself: the plugin
registers ``pre_tool_call`` / ``post_tool_call`` / ``on_session_start``, never
``pre_llm_call``. So once sensitive data is in an agent's context, a *cloud*
model transmits it off-box on the next turn. D3 closes this by configuration:
the profile must point at a local inference endpoint. This predicate makes that
requirement checkable, so a profile edit cannot silently reopen the leak.

The predicate is generic (no banking specifics) and reusable by any profile, so
it does not violate the "no banking names in the library" invariant. It lives in
core ``petasos/`` rather than the reference plugin because a profile's CI must
``import`` it from the pip-installed package. It is deliberately NOT added to
``petasos.__all__`` (the frozen public-API surface); import it module-qualified::

    from petasos.profile_lint import is_local_inference_endpoint

No new dependencies: stdlib ``urllib.parse`` + ``ipaddress`` only.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

# Provider names that denote a local inference server. ``base_url``, when
# present, is always authoritative over this fallback; the allowlist only
# decides the provider-only case. Compared after ``.strip().lower()``.
_LOCAL_PROVIDERS = frozenset({"lmstudio", "llama.cpp", "llamacpp", "ollama", "local", "localai"})


def is_local_inference_endpoint(provider: str | None, base_url: str | None) -> bool:
    """True iff the resolved inference endpoint is on the local box.

    Fail-secure: ambiguous or unrecognized inputs return False, because the
    caller uses this as a release-blocker gate ("financial data must not
    egress the box"). The verdict errs toward "not local".
    """
    base = (base_url or "").strip()
    provider_name = (provider or "").strip()

    # 1. None/empty guard first, so the step-3 provider fallback never runs
    #    ``.strip()`` on None and the predicate always returns a bool.
    if not base and not provider_name:
        return False

    # 2. base_url is authoritative when non-blank. (A whitespace-only base_url
    #    has already collapsed to "" above and falls through to step 3.)
    if base:
        try:
            host = urlsplit(base).hostname
        except ValueError:
            # Malformed URL (e.g. an unclosed IPv6 bracket "http://[::1"):
            # treat as not-local.
            return False
        if host is None:
            # No host component: a scheme-less "localhost:1234" (urlsplit reads
            # the token before the first ":" as the scheme) or a degenerate
            # "::::". urlsplit returns hostname=None without raising.
            return False
        # urlsplit already lowercases the host and strips IPv6 brackets. Strip a
        # single trailing dot so the absolute-FQDN form "localhost." is matched.
        if host.endswith("."):
            host = host[:-1]
        try:
            host_ip = ipaddress.ip_address(host)
        except ValueError:
            # host is a name, not an IP literal: only the exact "localhost" is
            # local. This closes the symmetric fail-open traps -- both
            # "127.0.0.1.evil.com" and "localhost.evil.com" are names (not IP
            # literals, not equal to "localhost"), as are "127.1" and a
            # zero-padded "127.0.0.01" (rejected by ipaddress). A
            # ``host.startswith("127.")`` test is forbidden: it is fail-open.
            return host == "localhost"
        # Loopback by IP-literal parsing, never by prefix/substring. ipv4_mapped
        # is handled explicitly so an IPv4-mapped loopback ("::ffff:127.0.0.1")
        # is recognized on every interpreter: the stdlib's own is_loopback
        # delegation to the mapped address is a 3.10.14+ / CVE-2024-4032
        # backport, absent on older 3.10.x. This only ever flips a mapped
        # *loopback* to True; a mapped LAN/routable address stays not-local.
        if isinstance(host_ip, ipaddress.IPv6Address):
            mapped = host_ip.ipv4_mapped
            if mapped is not None:
                return mapped.is_loopback
        return host_ip.is_loopback

    # 3. base_url absent/empty -> provider fallback against the documented
    #    local-server allowlist. Any other provider (anthropic, openai,
    #    openrouter, huggingface, unknown) is not local.
    return provider_name.lower() in _LOCAL_PROVIDERS
