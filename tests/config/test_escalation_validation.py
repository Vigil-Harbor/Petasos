"""Regression coverage for behavioral-spec features that the audit (features-tracker.xlsx)
flagged as untested ("NONE FOUND" / COVERAGE GAP), plus one field-attribution bug (DEF-02).

These lock load-bearing behaviors that previously had no direct test:
security-relevant reject branches (HMAC token verification, fail-secure escalation),
the PET-126 hot-reload `apply_config` surfaces, listener fan-out, and serialization
contracts. Every test here exercises a real code path (no mocks of the unit under test).
"""

from __future__ import annotations

import pytest

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig


# --- CFG-03: tier-threshold construction validation ---
def test_non_ascending_tiers_rejected_at_construction() -> None:
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
    with pytest.raises(ValueError):
        from_mapping(
            PetasosConfig,
            {
                "escalation": {
                    "tier3": float("inf"),
                },
            },
        )
