"""ToolCallGuard evasion (PET-14 GUARD-*)."""

from __future__ import annotations

from types import MappingProxyType

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


def test_whitespace_stripped_after_alias_lookup() -> None:
    """GUARD-02: ' bash ' does not map to exec alias (strip is last)."""
    from petasos.config import PetasosConfig
    from petasos.pipeline import Pipeline
    from petasos.premium.frequency import FrequencyTracker

    cfg = PetasosConfig()
    guard = ToolCallGuard(Pipeline(config=cfg), FrequencyTracker(cfg), cfg)
    assert guard._normalize_tool_name(" bash ") == "bash"
    assert guard._normalize_tool_name(" bash ") != "exec"


def test_profile_alias_maps_exec_to_read_exempt() -> None:
    """GUARD-03: profile can alias dangerous tool name to exempt 'read'."""
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
    from petasos.pipeline import Pipeline
    from petasos.premium.frequency import FrequencyTracker

    cfg = PetasosConfig()
    guard = ToolCallGuard(Pipeline(config=cfg), FrequencyTracker(cfg), cfg, profile=profile)
    assert guard._normalize_tool_name("exec") == "read"
