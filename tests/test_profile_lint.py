"""Pin local inference endpoint recognition without hostname-prefix lookalikes.

See docs/architecture/rationale.md, "Test timing and backend qualification"."""

from __future__ import annotations

from typing import Any

import pytest

from petasos.profile_lint import is_local_inference_endpoint

_CASES: list[tuple[str | None, str | None, bool]] = [
    ("", "http://127.0.0.1:1234/v1", True),
    ("", "http://localhost:8080", True),
    ("", "http://[::1]:1234", True),
    ("", "http://127.0.0.5:1234", True),
    ("", "http://LOCALHOST:1234", True),
    ("", "http://localhost.:8080", True),
    ("", "http://[::ffff:127.0.0.1]:1234", True),
    ("lmstudio", "", True),
    ("ollama", "", True),
    ("llama.cpp", "", True),
    ("  Ollama  ", "", True),
    ("ollama", "   ", True),
    ("", "https://api.anthropic.com", False),
    ("", "https://api.openai.com", False),
    ("", "https://openrouter.ai/api/v1", False),
    ("", "http://127.0.0.1.evil.com/", False),
    ("", "http://127.0.0.1.example.com:1234", False),
    ("", "https://localhost.evil.com/", False),
    ("", "http://0.0.0.0:1234", False),
    ("", "http://192.168.1.10:1234", False),
    ("", "http://10.0.0.4:1234", False),
    ("", "http://127.1:1234", False),
    ("", "http://127.0.0.01:1234", False),
    ("anthropic", "", False),
    ("openai", "", False),
    ("unknown", "", False),
    (None, None, False),
    ("", "", False),
    (None, "", False),
    ("", None, False),
    ("anthropic", "::::", False),
    ("anthropic", "http://[::1", False),
    ("anthropic", "localhost:1234", False),
]


@pytest.mark.parametrize(("provider", "base_url", "expected"), _CASES)
def test_is_local_inference_endpoint(
    provider: str | None, base_url: str | None, expected: bool
) -> None:
    """Pin is local inference endpoint."""
    assert is_local_inference_endpoint(provider, base_url) is expected


def _gavin_profile() -> dict[str, Any]:
    """A Gavin-shaped Hermes profile dict (constructed inline, no PyYAML dep).

    See docs/architecture/rationale.md, "Test timing and backend qualification"."""
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
    """Pin gavin profile is local inference."""
    profile = _gavin_profile()

    model = profile["model"]
    assert is_local_inference_endpoint(model["provider"], model["base_url"]) is True

    petasos_cfg = profile["petasos"]
    assert "mcp_bank_" in petasos_cfg["source_taint_namespaces"]
    assert petasos_cfg["egress_sink_tools"]
    assert petasos_cfg["anonymize"] is True

    profile["model"] = {"provider": "anthropic", "base_url": "https://api.anthropic.com"}
    cloud = profile["model"]
    assert is_local_inference_endpoint(cloud["provider"], cloud["base_url"]) is False
