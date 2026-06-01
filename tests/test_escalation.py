from __future__ import annotations

import pytest

from petasos.config import PetasosConfig
from petasos.session.escalation import (
    TIER3_FLOOR,
    evaluate_escalation,
    evaluate_tier,
)


def _cfg(**overrides: object) -> PetasosConfig:
    defaults: dict[str, object] = {
        "frequency_enabled": True,
        "escalation_enabled": True,
    }
    defaults.update(overrides)
    return PetasosConfig(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tier evaluation
# ---------------------------------------------------------------------------


class TestEvaluateTier:
    def test_below_tier1_returns_none(self) -> None:
        cfg = _cfg()
        assert evaluate_tier(0.0, cfg) == "none"
        assert evaluate_tier(14.9, cfg) == "none"

    def test_at_tier1_returns_tier1(self) -> None:
        cfg = _cfg()
        assert evaluate_tier(15.0, cfg) == "tier1"

    def test_between_tier1_and_tier2_returns_tier1(self) -> None:
        cfg = _cfg()
        assert evaluate_tier(20.0, cfg) == "tier1"

    def test_at_tier2_returns_tier2(self) -> None:
        cfg = _cfg()
        assert evaluate_tier(30.0, cfg) == "tier2"

    def test_between_tier2_and_tier3_returns_tier2(self) -> None:
        cfg = _cfg()
        assert evaluate_tier(40.0, cfg) == "tier2"

    def test_at_tier3_returns_tier3(self) -> None:
        cfg = _cfg()
        assert evaluate_tier(50.0, cfg) == "tier3"

    def test_above_tier3_returns_tier3(self) -> None:
        cfg = _cfg()
        assert evaluate_tier(999.0, cfg) == "tier3"


# ---------------------------------------------------------------------------
# Tier 3 floor
# ---------------------------------------------------------------------------


class TestTier3Floor:
    def test_tier3_below_floor_raises(self) -> None:
        with pytest.raises(ValueError, match="tier3 must be"):
            _cfg(tier3_threshold=29.0, tier2_threshold=20.0)

    def test_tier3_at_floor_accepted(self) -> None:
        cfg = _cfg(tier1_threshold=10.0, tier2_threshold=20.0, tier3_threshold=30.0)
        assert cfg.tier3_threshold == 30.0

    def test_floor_constant_is_30(self) -> None:
        assert TIER3_FLOOR == 30.0


# ---------------------------------------------------------------------------
# Escalation result
# ---------------------------------------------------------------------------


class TestEvaluateEscalation:
    def test_tier1_action_is_deep_inspect(self) -> None:
        cfg = _cfg()
        result = evaluate_escalation(15.0, cfg)
        assert result.tier == "tier1"
        assert result.action == "deep_inspect"
        assert result.threshold_crossed == 15.0

    def test_tier2_action_is_enhanced_scrutiny(self) -> None:
        cfg = _cfg()
        result = evaluate_escalation(30.0, cfg)
        assert result.tier == "tier2"
        assert result.action == "enhanced_scrutiny"
        assert result.threshold_crossed == 30.0

    def test_tier3_action_is_terminate(self) -> None:
        cfg = _cfg()
        result = evaluate_escalation(50.0, cfg)
        assert result.tier == "tier3"
        assert result.action == "terminate"
        assert result.threshold_crossed == 50.0

    def test_no_escalation_action_is_none(self) -> None:
        cfg = _cfg()
        result = evaluate_escalation(0.0, cfg)
        assert result.tier == "none"
        assert result.action == "none"
        assert result.threshold_crossed is None

    def test_escalation_result_is_frozen(self) -> None:
        cfg = _cfg()
        result = evaluate_escalation(15.0, cfg)
        with pytest.raises(AttributeError):
            result.tier = "modified"  # type: ignore[misc]
