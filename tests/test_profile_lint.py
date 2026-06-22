"""PET-133: unit tests for the D3 local-inference lint predicate.

Backend-free (no Presidio / LLM-Guard / LlamaFirewall import): runs on any
interpreter with Petasos importable. Covers ``is_local_inference_endpoint``
table-driven (at least one row per contract clause) plus the Gavin-shaped
profile gate (``test_gavin_profile_is_local_inference``).
"""

from __future__ import annotations

from typing import Any

import pytest

from petasos.profile_lint import is_local_inference_endpoint

# (provider, base_url, expected). At least one row per D3 contract clause.
_CASES: list[tuple[str | None, str | None, bool]] = [
    # --- local via base_url (authoritative when non-blank) ---
    ("", "http://127.0.0.1:1234/v1", True),
    ("", "http://localhost:8080", True),
    ("", "http://[::1]:1234", True),
    ("", "http://127.0.0.5:1234", True),  # all of 127.0.0.0/8 is loopback
    ("", "http://LOCALHOST:1234", True),  # host lowercased by urlsplit
    ("", "http://localhost.:8080", True),  # absolute-FQDN trailing dot stripped
    ("", "http://[::ffff:127.0.0.1]:1234", True),  # IPv4-mapped IPv6 loopback
    # --- local via provider fallback (empty/blank base_url) ---
    ("lmstudio", "", True),
    ("ollama", "", True),
    ("llama.cpp", "", True),
    ("  Ollama  ", "", True),  # .strip().lower() normalization
    ("ollama", "   ", True),  # whitespace-only base_url -> provider fallback
    # --- not local: cloud endpoints (fail-secure) ---
    ("", "https://api.anthropic.com", False),
    ("", "https://api.openai.com", False),
    ("", "https://openrouter.ai/api/v1", False),
    # --- not local: host-parse fail-open traps (the P0 regression) ---
    ("", "http://127.0.0.1.evil.com/", False),
    ("", "http://127.0.0.1.example.com:1234", False),
    ("", "https://localhost.evil.com/", False),
    # --- not local: non-loopback IP literals ---
    ("", "http://0.0.0.0:1234", False),
    ("", "http://192.168.1.10:1234", False),
    ("", "http://10.0.0.4:1234", False),
    ("", "http://127.1:1234", False),  # dotted-shorthand: not a valid literal
    ("", "http://127.0.0.01:1234", False),  # zero-padded octet rejected
    # --- not local: provider fallback misses ---
    ("anthropic", "", False),
    ("openai", "", False),
    ("unknown", "", False),
    # --- not local: None/empty guard (runs first) ---
    (None, None, False),
    ("", "", False),
    (None, "", False),
    ("", None, False),
    # --- not local: degenerate base_url shapes ---
    ("anthropic", "::::", False),  # urlsplit hostname=None, does NOT raise
    ("anthropic", "http://[::1", False),  # malformed IPv6 bracket -> ValueError
    ("anthropic", "localhost:1234", False),  # scheme-less -> hostname=None
]


@pytest.mark.parametrize(("provider", "base_url", "expected"), _CASES)
def test_is_local_inference_endpoint(
    provider: str | None, base_url: str | None, expected: bool
) -> None:
    # ``is`` (not ``==``): the predicate must always return a genuine bool.
    assert is_local_inference_endpoint(provider, base_url) is expected


def _gavin_profile() -> dict[str, Any]:
    """A Gavin-shaped Hermes profile dict (constructed inline, no PyYAML dep).

    The ``model:`` endpoint is local; the ``petasos:`` section pins the D4 +
    PET-134 taint wiring at the config level. Gavin's own profile CI runs the
    same ``is_local_inference_endpoint`` helper against the real YAML.
    """
    return {
        "model": {
            "provider": "lmstudio",
            "base_url": "http://127.0.0.1:1234/v1",
        },
        "petasos": {
            "source_taint_namespaces": ["mcp_bank_"],
            "egress_sink_tools": [
                "send_email",
                "http_request",
                "mcp_vigil_harbor_memory_ingest",
            ],
            "anonymize": True,
        },
    }


def test_gavin_profile_is_local_inference() -> None:
    profile = _gavin_profile()

    # D3 hard gate: the local-endpoint profile passes the lint.
    model = profile["model"]
    assert is_local_inference_endpoint(model["provider"], model["base_url"]) is True

    # D4 + PET-134 taint wiring pinned at the config level.
    petasos_cfg = profile["petasos"]
    assert "mcp_bank_" in petasos_cfg["source_taint_namespaces"]
    assert petasos_cfg["egress_sink_tools"]  # non-empty
    assert petasos_cfg["anonymize"] is True

    # The same dict mutated to a cloud provider fails the gate, so a profile
    # edit cannot silently reopen the inference leak.
    profile["model"] = {"provider": "anthropic", "base_url": "https://api.anthropic.com"}
    cloud = profile["model"]
    assert is_local_inference_endpoint(cloud["provider"], cloud["base_url"]) is False
