"""Standalone tier-3 safety net fires when frequency tracking is off."""

from __future__ import annotations

from typing import Any

import pytest

from petasos.config.schema import ConfigError, from_mapping, merge
from petasos.config.sections import PetasosConfig
from petasos.model import Severity
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner


def _cfg(changes: dict[str, Any] | None = None) -> PetasosConfig:
    document: dict[str, Any] = {
        "frequency": {"enabled": False},
        "escalation": {"enabled": False},
    }
    if changes:
        document = merge(document, changes)
    return from_mapping(PetasosConfig, document)


def _payload_3_critical() -> str:
    binary = "\x01" * 10
    depth = "[" * 20 + "]" * 20
    padding = "A" * 600_000
    return binary + depth + padding


async def test_tier3_fires_without_frequency() -> None:
    scanner = MinimalScanner(max_payload_bytes=100, max_json_depth=5)
    cfg = _cfg()
    pipe = Pipeline(scanners=[scanner], config=cfg)
    result = await pipe.inspect(_payload_3_critical())
    critical_count = sum(1 for f in result.findings if f.severity == Severity.CRITICAL)
    assert critical_count >= 3
    assert result.escalation_tier == "tier3"
    assert result.safe is False


async def test_below_threshold_no_tier3() -> None:
    scanner = MinimalScanner(max_payload_bytes=100, max_json_depth=5)
    cfg = _cfg({"escalation": {"enabled": True}})
    pipe = Pipeline(scanners=[scanner], config=cfg)
    result = await pipe.inspect("\x01" * 10 + "[" * 20 + "]" * 20)
    critical_count = sum(1 for f in result.findings if f.severity == Severity.CRITICAL)
    assert critical_count == 2
    assert result.escalation_tier is None


async def test_standalone_idempotent_with_frequency() -> None:
    scanner = MinimalScanner(max_payload_bytes=100, max_json_depth=5)
    cfg = _cfg({"frequency": {"enabled": True}, "escalation": {"enabled": True, "tier3": 50.0}})
    pipe = Pipeline(scanners=[scanner], config=cfg)
    for _ in range(6):
        result = await pipe.inspect(_payload_3_critical(), session_id="s1")
    assert result.escalation_tier == "tier3"
    assert result.safe is False


async def test_standalone_survives_severity_override() -> None:
    scanner = MinimalScanner(max_payload_bytes=100, max_json_depth=5)
    hostile = {
        "frequency": {"enabled": False},
        "escalation": {"enabled": True},
        "rules": {
            "severity_overrides": {
                "petasos.syntactic.structural.binary-content": "low",
                "petasos.syntactic.structural.excessive-depth": "low",
                "petasos.syntactic.structural.oversized-payload": "low",
            }
        },
    }
    with pytest.raises(ConfigError, match="structural"):
        from_mapping(PetasosConfig, hostile)
    # The refused overrides never apply. The payload still reaches tier 3.
    pipe = Pipeline(scanners=[scanner], config=_cfg({"escalation": {"enabled": True}}))
    result = await pipe.inspect(_payload_3_critical())
    assert result.escalation_tier == "tier3"
    assert result.safe is False
