"""ToolCallGuard evasion (PET-14 GUARD-*)."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from petasos.config import PetasosConfig
from petasos.premium.guard import ToolCallGuard
from petasos.premium.profiles import ResolvedProfile


def _guard_with_profile(profile: ResolvedProfile) -> ToolCallGuard:
    from petasos.pipeline import Pipeline
    from petasos.premium.frequency import FrequencyTracker

    cfg = PetasosConfig(tool_guard_enabled=True, frequency_enabled=True)
    pipe = Pipeline(config=cfg)
    # premium inactive without license — test normalization only
    return ToolCallGuard(pipe, FrequencyTracker(cfg), cfg, profile=profile)


def test_whitespace_stripped_before_alias_resolves() -> None:
    """GUARD-02: ' bash ' resolves to exec alias (strip runs before alias lookup)."""
    from petasos.config import PetasosConfig
    from petasos.pipeline import Pipeline
    from petasos.premium.frequency import FrequencyTracker

    cfg = PetasosConfig()
    guard = ToolCallGuard(Pipeline(config=cfg), FrequencyTracker(cfg), cfg)
    assert guard._normalize_tool_name(" bash ") == "exec"


def test_cyrillic_a_in_bash_normalizes() -> None:
    """GUARD-02: Cyrillic а (U+0430) in 'bаsh' maps to 'exec' via homoglyph table."""
    from petasos.config import PetasosConfig
    from petasos.pipeline import Pipeline
    from petasos.premium.frequency import FrequencyTracker

    cfg = PetasosConfig()
    guard = ToolCallGuard(Pipeline(config=cfg), FrequencyTracker(cfg), cfg)
    assert guard._normalize_tool_name("bаsh") == "exec"


def test_fullwidth_bash_normalizes() -> None:
    """GUARD-02: fullwidth 'ｂａｓｈ' normalizes to 'exec' via NFKC + alias."""
    from petasos.config import PetasosConfig
    from petasos.pipeline import Pipeline
    from petasos.premium.frequency import FrequencyTracker

    cfg = PetasosConfig()
    guard = ToolCallGuard(Pipeline(config=cfg), FrequencyTracker(cfg), cfg)
    assert guard._normalize_tool_name("ｂａｓｈ") == "exec"


def test_mixed_script_shell_normalizes() -> None:
    """GUARD-02: Cyrillic ѕ (U+0455) in 'ѕhell' maps to 'exec' via homoglyph table."""
    from petasos.config import PetasosConfig
    from petasos.pipeline import Pipeline
    from petasos.premium.frequency import FrequencyTracker

    cfg = PetasosConfig()
    guard = ToolCallGuard(Pipeline(config=cfg), FrequencyTracker(cfg), cfg)
    assert guard._normalize_tool_name("ѕhell") == "exec"


def test_invisible_chars_not_stripped() -> None:
    """GUARD-02 boundary: zero-width space is NOT stripped (out of scope)."""
    from petasos.config import PetasosConfig
    from petasos.pipeline import Pipeline
    from petasos.premium.frequency import FrequencyTracker

    cfg = PetasosConfig()
    guard = ToolCallGuard(Pipeline(config=cfg), FrequencyTracker(cfg), cfg)
    assert guard._normalize_tool_name("ba​sh") != "exec"


def test_profile_alias_maps_exec_to_read_exempt() -> None:
    """GUARD-03: profile alias exec->read + exempt read is neutralized at runtime."""
    profile = ResolvedProfile(
        name="evil",
        suppress_rules=frozenset(),
        severity_overrides=MappingProxyType({}),
        confidence_floor=0.0,
        tier_thresholds=None,
        pii_entities_extra=(),
        tool_exempt_list=frozenset({"read"}),
        tool_alias_map=MappingProxyType({"exec": "read"}),
    )
    guard = _guard_with_profile(profile)
    assert guard._normalize_tool_name("exec") == "exec"


def test_alias_onto_exempt_runtime_fallback() -> None:
    """GUARD-03: directly-built ResolvedProfile with exec->read + exempt read
    falls back to un-aliased name (defense-in-depth for construction bypass)."""
    profile = ResolvedProfile(
        name="bypass",
        suppress_rules=frozenset(),
        severity_overrides=MappingProxyType({}),
        confidence_floor=0.0,
        tier_thresholds=None,
        pii_entities_extra=(),
        tool_exempt_list=frozenset({"read"}),
        tool_alias_map=MappingProxyType({"exec": "read"}),
    )
    guard = _guard_with_profile(profile)
    assert guard._normalize_tool_name("exec") == "exec"


@pytest.mark.asyncio
async def test_alias_exec_to_read_exempt_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """GUARD-03 end-to-end: with premium active, exec->read + exempt read
    does NOT short-circuit as exempt — params are scanned under true identity."""
    from petasos.pipeline import Pipeline
    from petasos.premium.frequency import FrequencyTracker

    profile = ResolvedProfile(
        name="evil",
        suppress_rules=frozenset(),
        severity_overrides=MappingProxyType({}),
        confidence_floor=0.0,
        tier_thresholds=None,
        pii_entities_extra=(),
        tool_exempt_list=frozenset({"read"}),
        tool_alias_map=MappingProxyType({"exec": "read"}),
    )
    cfg = PetasosConfig(tool_guard_enabled=True, frequency_enabled=True)
    pipe = Pipeline(config=cfg)
    monkeypatch.setattr(pipe, "is_premium_active", lambda _feature: True)
    guard = ToolCallGuard(pipe, FrequencyTracker(cfg), cfg, profile=profile)
    result = await guard.evaluate("exec", {"command": "ls"}, "s1")
    assert result.reason not in ("premium inactive", "tool exempt per profile")


def test_whitespace_alias_onto_exempt_runtime_fallback() -> None:
    """GUARD-03: whitespace-padded alias value ' read ' still triggers fallback."""
    profile = ResolvedProfile(
        name="ws-bypass",
        suppress_rules=frozenset(),
        severity_overrides=MappingProxyType({}),
        confidence_floor=0.0,
        tier_thresholds=None,
        pii_entities_extra=(),
        tool_exempt_list=frozenset({"read"}),
        tool_alias_map=MappingProxyType({"exec": " read "}),
    )
    guard = _guard_with_profile(profile)
    assert guard._normalize_tool_name("exec") == "exec"
