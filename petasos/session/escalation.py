"""Derive escalation tiers with an independent termination floor."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, cast

from petasos.config.floors import TIER3_FLOOR as TIER3_FLOOR

_logger = logging.getLogger(__name__)

_TIER_ACTIONS: dict[str, str] = {
    "none": "none",
    "tier1": "deep_inspect",
    "tier2": "enhanced_scrutiny",
    "tier3": "terminate",
}

_TIER_RANK: dict[str, int] = {"none": 0, "tier1": 1, "tier2": 2, "tier3": 3}


def max_tier(*tiers: str) -> str:
    """Return the most restrictive tier, rejecting unknown tier values."""
    best = "none"
    best_rank = 0
    for tier in tiers:
        rank = _TIER_RANK.get(tier)
        if rank is None:
            raise ValueError(f"unknown tier: {tier!r}")
        if rank > best_rank:
            best_rank = rank
            best = tier
    return best


@dataclass(frozen=True)
class EscalationResult:
    """Record a tier, its action and the threshold crossed."""

    tier: str
    action: str
    threshold_crossed: float | None


def derive_tier(score: float, tier1: float, tier2: float, tier3: float) -> str:
    """Return the score-derived tier while enforcing the literal termination floor."""
    if not math.isfinite(score):
        return "tier3"
    # An inline floor resists rebinding the exported validation constant.
    if score >= max(tier3, 30.0):
        return "tier3"
    if score >= tier2:
        return "tier2"
    if score >= tier1:
        return "tier1"
    return "none"


def _tiers(config: object) -> tuple[float, float, float]:
    """Escalation scores from a tree, an escalation section, or a flat config."""
    raw = cast("Any", config)
    escalation = getattr(raw, "escalation", None)
    if escalation is not None and hasattr(escalation, "tier1"):
        return (float(escalation.tier1), float(escalation.tier2), float(escalation.tier3))
    if hasattr(raw, "tier1") and hasattr(raw, "tier3"):
        return (float(raw.tier1), float(raw.tier2), float(raw.tier3))
    return (float(raw.tier1_threshold), float(raw.tier2_threshold), float(raw.tier3_threshold))


def evaluate_tier(score: float, config: object) -> str:
    """Return the escalation tier for ``score`` under ``config``'s thresholds."""
    tier1, tier2, tier3 = _tiers(config)
    if not math.isfinite(tier3) or tier3 < TIER3_FLOOR:
        _logger.warning(
            "tier3_threshold %r is non-finite or below floor; returning tier3 fail-secure",
            tier3,
        )
        return "tier3"
    return derive_tier(score, tier1, tier2, tier3)


def evaluate_escalation(score: float, config: object) -> EscalationResult:
    """Return the tier, the action it names, and the threshold the score crossed."""
    tier = evaluate_tier(score, config)
    action = _TIER_ACTIONS[tier]
    tier1, tier2, tier3 = _tiers(config)
    if tier == "tier3":
        threshold_crossed: float | None = tier3
    elif tier == "tier2":
        threshold_crossed = tier2
    elif tier == "tier1":
        threshold_crossed = tier1
    else:
        threshold_crossed = None
    return EscalationResult(tier=tier, action=action, threshold_crossed=threshold_crossed)
