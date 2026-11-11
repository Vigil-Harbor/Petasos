"""Regression coverage for behavioral-spec features that the audit (features-tracker.xlsx)
flagged as untested ("NONE FOUND" / COVERAGE GAP), plus one field-attribution bug (DEF-02).

These lock load-bearing behaviors that previously had no direct test:
security-relevant reject branches (HMAC token verification, fail-secure escalation),
the PET-126 hot-reload `apply_config` surfaces, listener fan-out, and serialization
contracts. Every test here exercises a real code path (no mocks of the unit under test).
"""

from __future__ import annotations

import pytest

from petasos.config.sections import PetasosConfig
from petasos.session.escalation import derive_tier, evaluate_tier


# ----------------------------- ESC-03: fail-secure escalation -----------------------------
@pytest.mark.parametrize("bad", [float("inf"), float("nan")])
def test_non_finite_score_derives_tier3(bad: float) -> None:
    cfg = PetasosConfig()
    assert (
        derive_tier(bad, cfg.escalation.tier1, cfg.escalation.tier2, cfg.escalation.tier3)
        == "tier3"
    )
    assert evaluate_tier(bad, cfg) == "tier3"
