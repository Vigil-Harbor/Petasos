"""PET-75 ESC-01: Standalone tier-3 safety net fires regardless of license/frequency state."""

from __future__ import annotations

from types import MappingProxyType

from petasos._types import Severity
from petasos.config import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner


def _cfg(**overrides: object) -> PetasosConfig:
    defaults: dict[str, object] = {
        "frequency_enabled": False,
        "escalation_enabled": False,
    }
    defaults.update(overrides)
    return PetasosConfig(**defaults)  # type: ignore[arg-type]


def _payload_3_critical() -> str:
    binary = "\x01" * 10
    depth = "[" * 20 + "]" * 20
    padding = "A" * 600_000
    return binary + depth + padding


async def test_tier3_fires_without_frequency() -> None:
    scanner = MinimalScanner(max_payload_bytes=100, max_json_depth=5)
    cfg = _cfg(frequency_enabled=False, escalation_enabled=False)
    pipe = Pipeline(scanners=[scanner], config=cfg)
    result = await pipe.inspect(_payload_3_critical())
    critical_count = sum(1 for f in result.findings if f.severity == Severity.CRITICAL)
    assert critical_count >= 3
    assert result.escalation_tier == "tier3"
    assert result.safe is False


async def test_tier3_fires_without_license() -> None:
    scanner = MinimalScanner(max_payload_bytes=100, max_json_depth=5)
    cfg = _cfg()
    pipe = Pipeline(scanners=[scanner], config=cfg)
    result = await pipe.inspect(_payload_3_critical())
    assert result.escalation_tier == "tier3"
    assert result.safe is False


async def test_below_threshold_no_tier3(valid_key: str) -> None:
    scanner = MinimalScanner(max_payload_bytes=100, max_json_depth=5)
    cfg = _cfg(frequency_enabled=False, escalation_enabled=True)
    pipe = Pipeline(scanners=[scanner], config=cfg)
    pipe.activate(valid_key)
    result = await pipe.inspect("\x01" * 10 + "[" * 20 + "]" * 20)
    critical_count = sum(1 for f in result.findings if f.severity == Severity.CRITICAL)
    assert critical_count == 2
    assert result.escalation_tier is None


async def test_standalone_idempotent_with_frequency(valid_key: str) -> None:
    scanner = MinimalScanner(max_payload_bytes=100, max_json_depth=5)
    cfg = _cfg(
        frequency_enabled=True,
        escalation_enabled=True,
        tier3_threshold=50.0,
    )
    pipe = Pipeline(scanners=[scanner], config=cfg)
    pipe.activate(valid_key)
    for _ in range(6):
        result = await pipe.inspect(_payload_3_critical(), session_id="s1")
    assert result.escalation_tier == "tier3"
    assert result.safe is False


async def test_standalone_survives_severity_override(valid_key: str) -> None:
    from petasos.session.profiles import ResolvedProfile

    scanner = MinimalScanner(max_payload_bytes=100, max_json_depth=5)
    cfg = _cfg(frequency_enabled=False, escalation_enabled=True)
    pipe = Pipeline(scanners=[scanner], config=cfg)
    pipe.activate(valid_key)
    profile = ResolvedProfile(
        name="test",
        suppress_rules=frozenset(),
        severity_overrides=MappingProxyType(
            {
                "petasos.syntactic.structural.binary-content": "low",
                "petasos.syntactic.structural.excessive-depth": "low",
                "petasos.syntactic.structural.oversized-payload": "low",
            }
        ),
        confidence_floor=0.0,
        tier_thresholds=None,
        pii_entities_extra=(),
        tool_exempt_list=frozenset(),
        tool_alias_map=MappingProxyType({}),
    )
    result = await pipe.inspect(_payload_3_critical(), profile=profile)
    assert result.escalation_tier == "tier3"
    assert result.safe is False
