"""PET-75 ESC-03: Shared derive_tier() helper and guard integration."""

from __future__ import annotations

from types import MappingProxyType
from unittest.mock import patch

from petasos.config import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.session.escalation import derive_tier, evaluate_tier
from petasos.session.frequency import FrequencyTracker
from petasos.session.guard import ToolCallGuard
from petasos.session.profiles import ResolvedProfile, TierThresholds


def _cfg(**overrides: object) -> PetasosConfig:
    defaults: dict[str, object] = {
        "frequency_enabled": True,
        "escalation_enabled": True,
        "tool_guard_enabled": True,
    }
    defaults.update(overrides)
    return PetasosConfig(**defaults)  # type: ignore[arg-type]


class TestDeriveTierBoundaries:
    def test_derive_tier_boundaries(self) -> None:
        t1, t2, t3 = 15.0, 30.0, 50.0
        assert derive_tier(14.9, t1, t2, t3) == "none"
        assert derive_tier(15.0, t1, t2, t3) == "tier1"
        assert derive_tier(29.9, t1, t2, t3) == "tier1"
        assert derive_tier(30.0, t1, t2, t3) == "tier2"
        assert derive_tier(49.9, t1, t2, t3) == "tier2"
        assert derive_tier(50.0, t1, t2, t3) == "tier3"
        assert derive_tier(100.0, t1, t2, t3) == "tier3"

    def test_derive_tier_nan_fails_closed(self) -> None:
        assert derive_tier(float("nan"), 15.0, 30.0, 50.0) == "tier3"

    def test_derive_tier_inf_fails_closed(self) -> None:
        assert derive_tier(float("inf"), 15.0, 30.0, 50.0) == "tier3"
        assert derive_tier(float("-inf"), 15.0, 30.0, 50.0) == "tier3"

    def test_evaluate_tier_delegates(self) -> None:
        cfg = _cfg()
        for score in [0.0, 14.9, 15.0, 30.0, 50.0, 100.0]:
            expected = derive_tier(
                score, cfg.tier1_threshold, cfg.tier2_threshold, cfg.tier3_threshold
            )
            assert evaluate_tier(score, cfg) == expected


class TestGuardDeriveTier:
    async def test_guard_with_profile_thresholds(self, valid_key: str) -> None:
        cfg = _cfg(tier1_threshold=15.0, tier2_threshold=30.0, tier3_threshold=50.0)
        pipe = Pipeline(config=cfg)
        pipe.activate(valid_key)
        tracker = FrequencyTracker(cfg)

        profile = ResolvedProfile(
            name="strict",
            suppress_rules=frozenset(),
            severity_overrides=MappingProxyType({}),
            confidence_floor=0.0,
            tier_thresholds=TierThresholds(tier1=5.0, tier2=10.0, tier3=30.0),
            pii_entities_extra=(),
            tool_exempt_list=frozenset(),
            tool_alias_map=MappingProxyType({}),
        )
        guard = ToolCallGuard(pipe, tracker, cfg, profile=profile)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.a"] * 2)

        result = await guard.evaluate("bash", {}, "s1")
        assert result.tier == "tier2"

    async def test_guard_without_profile_falls_back(self, valid_key: str) -> None:
        cfg = _cfg(tier1_threshold=15.0, tier2_threshold=30.0, tier3_threshold=50.0)
        pipe = Pipeline(config=cfg)
        pipe.activate(valid_key)
        tracker = FrequencyTracker(cfg)
        guard = ToolCallGuard(pipe, tracker, cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.a"] * 2)

        state = tracker.get_state("s1")
        assert state is not None
        expected_tier = evaluate_tier(state.last_score, cfg)

        result = await guard.evaluate("bash", {}, "s1")
        assert result.tier == expected_tier
