"""Pin fail-secure handling of nonfinite risk thresholds.

See docs/architecture/rationale.md, "Test timing and backend qualification"."""

from __future__ import annotations

import pytest

from petasos.config.sections import PetasosConfig
from petasos.session.escalation import derive_tier, evaluate_tier


@pytest.mark.parametrize("bad", [float("inf"), float("nan")])
def test_non_finite_score_derives_tier3(bad: float) -> None:
    """Pin non finite score derives tier3."""
    cfg = PetasosConfig()
    assert (
        derive_tier(bad, cfg.escalation.tier1, cfg.escalation.tier2, cfg.escalation.tier3)
        == "tier3"
    )
    assert evaluate_tier(bad, cfg) == "tier3"
