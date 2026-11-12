"""Pin validated session bounds and immutable configuration fields."""

from __future__ import annotations

import pytest

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig


class TestSessionConfigValidation:
    """Pin Session Config Validation."""

    def test_thresholds_not_ascending_raises(self) -> None:
        """Pin thresholds not ascending raises."""
        with pytest.raises(ValueError, match="strictly ascending"):
            from_mapping(
                PetasosConfig,
                {
                    "escalation": {
                        "tier1": 50.0,
                        "tier2": 30.0,
                        "tier3": 100.0,
                    },
                },
            )

    def test_valid_session_fields_accepted(self) -> None:
        """Pin valid session fields accepted."""
        cfg = from_mapping(
            PetasosConfig,
            {
                "frequency": {
                    "half_life_seconds": 30.0,
                    "rolling_window_seconds": 120.0,
                    "rolling_threshold": 5,
                },
                "escalation": {
                    "tier1": 10.0,
                    "tier2": 25.0,
                    "tier3": 40.0,
                },
                "sessions": {
                    "max": 5000,
                    "ttl_seconds": 1800.0,
                    "max_new_per_minute": 30,
                },
            },
        )
        assert cfg.escalation.tier1 == 10.0

    def test_negative_half_life_raises(self) -> None:
        """Pin negative half life raises."""
        with pytest.raises(ValueError, match="frequency.half_life_seconds"):
            from_mapping(
                PetasosConfig,
                {
                    "frequency": {
                        "half_life_seconds": -1.0,
                    },
                },
            )

    def test_negative_weight_raises(self) -> None:
        """Pin negative weight raises."""
        with pytest.raises(ValueError, match="frequency.weights"):
            from_mapping(
                PetasosConfig,
                {
                    "frequency": {
                        "weights": {"rule": -5.0},
                    },
                },
            )

    def test_infinite_threshold_raises(self) -> None:
        """Pin infinite threshold raises."""
        with pytest.raises(ValueError):
            from_mapping(
                PetasosConfig,
                {
                    "escalation": {
                        "tier1": 15.0,
                        "tier2": 30.0,
                        "tier3": float("inf"),
                    },
                },
            )
