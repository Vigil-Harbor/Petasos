"""Pin score-derived tiers and the independent termination floor."""

from __future__ import annotations

import pytest

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
from petasos.session import escalation
from petasos.session.escalation import (
    TIER3_FLOOR,
    derive_tier,
    evaluate_escalation,
    evaluate_tier,
)


def _cfg(partial: dict[str, object] | None = None) -> PetasosConfig:
    """Build a config tree from a partial document."""
    if not partial:
        return PetasosConfig()
    return from_mapping(PetasosConfig, partial)


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


class TestTier3Floor:
    def test_tier3_below_floor_raises(self) -> None:
        with pytest.raises(ValueError, match="escalation.tier3"):
            _cfg(
                {
                    "escalation": {
                        "tier3": 29.0,
                        "tier2": 20.0,
                    },
                }
            )

    def test_tier3_at_floor_accepted(self) -> None:
        cfg = _cfg(
            {
                "escalation": {
                    "tier1": 10.0,
                    "tier2": 20.0,
                    "tier3": 30.0,
                },
            }
        )
        assert cfg.escalation.tier3 == 30.0

    def test_floor_constant_is_30(self) -> None:
        assert TIER3_FLOOR == 30.0

    def test_hostile_config_cannot_lower_tier3_floor(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The literal floor survives both hostile thresholds and constant rebinding.

        monkeypatch.setattr(escalation, "TIER3_FLOOR", 0.0)
        assert derive_tier(30.0, 10.0, 20.0, 10.0) == "tier3"
        assert derive_tier(29.999, 10.0, 20.0, 10.0) != "tier3"

        assert derive_tier(30.0, 15.0, 25.0, 30.0) == "tier3"
        assert derive_tier(29.999, 15.0, 25.0, 30.0) != "tier3"

        # Tamper the frozen slot because validated construction rejects nonfinite thresholds.
        cfg = _cfg(
            {
                "escalation": {
                    "tier1": 15.0,
                    "tier2": 25.0,
                    "tier3": 30.0,
                },
            }
        )
        object.__setattr__(cfg.escalation, "tier3", float("nan"))
        assert evaluate_tier(50.0, cfg) == "tier3"

        with pytest.raises(ValueError):
            _cfg(
                {
                    "escalation": {
                        "tier3": float("nan"),
                    },
                }
            )

        # derive_tier checks nonfinite scores; evaluate_tier separately checks nonfinite
        # thresholds.
        assert derive_tier(float("nan"), 15.0, 25.0, 30.0) == "tier3"


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
