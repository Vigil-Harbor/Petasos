"""Pin ascending, finite escalation thresholds and the termination floor.

See docs/architecture/rationale.md, "Test timing and backend qualification"."""

from __future__ import annotations

import pytest

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig


def test_non_ascending_tiers_rejected_at_construction() -> None:
    """Pin non ascending tiers rejected at construction."""
    with pytest.raises(ValueError):
        from_mapping(
            PetasosConfig,
            {
                "escalation": {
                    "tier1": 50.0,
                    "tier2": 40.0,
                    "tier3": 60.0,
                },
            },
        )


def test_non_finite_tier_rejected_at_construction() -> None:
    """Pin non finite tier rejected at construction."""
    with pytest.raises(ValueError):
        from_mapping(
            PetasosConfig,
            {
                "escalation": {
                    "tier3": float("inf"),
                },
            },
        )
