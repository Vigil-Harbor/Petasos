"""Pin shared score-to-tier derivation in library and guard decisions."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from petasos.config.schema import from_mapping, merge
from petasos.config.sections import PetasosConfig
from petasos.guard.guard import ToolCallGuard
from petasos.pipeline import Pipeline
from petasos.session.escalation import derive_tier, evaluate_tier
from petasos.session.frequency import FrequencyTracker


def _cfg(changes: dict[str, Any] | None = None) -> PetasosConfig:
    document: dict[str, Any] = {
        "frequency": {"enabled": True},
        "escalation": {"enabled": True},
        "tools": {"enabled": True},
    }
    if changes:
        document = merge(document, changes)
    return from_mapping(PetasosConfig, document)


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
                score, cfg.escalation.tier1, cfg.escalation.tier2, cfg.escalation.tier3
            )
            assert evaluate_tier(score, cfg) == expected


class TestGuardDeriveTier:
    async def test_guard_ignores_profile_thresholds(self) -> None:
        cfg = _cfg({"escalation": {"tier1": 15.0, "tier2": 30.0, "tier3": 50.0}})
        pipe = Pipeline(config=cfg)
        tracker = FrequencyTracker(cfg)
        guard = ToolCallGuard(pipe, tracker, cfg)

        t0 = 1000.0
        with patch("petasos.session.frequency.time.monotonic", return_value=t0):
            tracker.update("s1", ["petasos.syntactic.injection.a"] * 2)

        result = await guard.evaluate("bash", {}, "s1")
        assert result.tier == "tier1"

    async def test_guard_without_profile_falls_back(self) -> None:
        cfg = _cfg({"escalation": {"tier1": 15.0, "tier2": 30.0, "tier3": 50.0}})
        pipe = Pipeline(config=cfg)
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
