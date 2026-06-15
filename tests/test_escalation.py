from __future__ import annotations

import pytest

from petasos.config import PetasosConfig
from petasos.session import escalation
from petasos.session.escalation import (
    TIER3_FLOOR,
    derive_tier,
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

    def test_hostile_config_cannot_lower_tier3_floor(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # PET-125 invariant pin: the Tier-3 floor survives a hostile *config*. A
        # relaxed-but-valid (or in-memory-tampered) tier3 threshold cannot lower
        # the enforced 30.0 floor, and the floor is moot only post-disarm (which
        # short-circuits enforcement before any scan — documented, not tested here).

        # (1) Finite sub-floor threshold + rebinding the named constant. derive_tier
        # uses the inline literal max(tier3, 30.0) (escalation.py:63), NOT the
        # imported TIER3_FLOOR name, so neither a sub-floor threshold passed directly
        # nor rebinding escalation.TIER3_FLOOR can drop the floor.
        monkeypatch.setattr(escalation, "TIER3_FLOOR", 0.0)
        assert derive_tier(30.0, 10.0, 20.0, 10.0) == "tier3"  # floored up to 30.0
        assert derive_tier(29.999, 10.0, 20.0, 10.0) != "tier3"  # below the floor

        # (2) Exact boundary: 30.0 is tier3 (>=), just below is not.
        assert derive_tier(30.0, 15.0, 25.0, 30.0) == "tier3"
        assert derive_tier(29.999, 15.0, 25.0, 30.0) != "tier3"

        # (3) Non-finite threshold fail-secure, via the config-facing evaluate_tier
        # (PET-23 isfinite guard, escalation.py:73). A real PetasosConfig rejects a
        # non-finite threshold at construction and is frozen+slots, so tamper an
        # otherwise-valid frozen instance through its existing slot.
        cfg = _cfg(tier1_threshold=15.0, tier2_threshold=25.0, tier3_threshold=30.0)
        object.__setattr__(cfg, "tier3_threshold", float("nan"))
        assert evaluate_tier(50.0, cfg) == "tier3"

        # And the config layer rejects it first.
        with pytest.raises(ValueError):
            _cfg(tier3_threshold=float("nan"))

        # derive_tier guards a NaN *score* (escalation.py:58-59) but NOT a NaN
        # *threshold* (that guard lives in evaluate_tier); pin only the score guard.
        assert derive_tier(float("nan"), 15.0, 25.0, 30.0) == "tier3"


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
