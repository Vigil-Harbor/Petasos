from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from petasos.config import PetasosConfig

from petasos.config import TIER3_FLOOR as TIER3_FLOOR

_logger = logging.getLogger(__name__)

_TIER_ACTIONS: dict[str, str] = {
    "none": "none",
    "tier1": "deep_inspect",
    "tier2": "enhanced_scrutiny",
    "tier3": "terminate",
}

# PET-107: single ordering source for tier comparison across the codebase.
_TIER_RANK: dict[str, int] = {"none": 0, "tier1": 1, "tier2": 2, "tier3": 3}


def max_tier(*tiers: str) -> str:
    """Return the highest-ranked tier among the inputs (``"none"`` if none given).

    The single ordering source for combining already-derived tier strings
    (e.g. an own tier with a parent-chain of ancestor tiers, PET-107 Option A).
    It is a *combinator*, not a re-derivation: it never re-evaluates a score and
    never re-applies the tier-3 floor (that stays inline in ``derive_tier``).

    Raises ``ValueError`` on any string not in ``_TIER_RANK``. The inputs are
    produced internally, so an unknown value is a bug — ranking it silently as
    ``"none"`` would be a fail-open in a security max, which is never acceptable.
    """
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
    tier: str
    action: str
    threshold_crossed: float | None


def derive_tier(score: float, tier1: float, tier2: float, tier3: float) -> str:
    if not math.isfinite(score):
        return "tier3"
    # PET-23: the floor is an inline literal, NOT the imported TIER3_FLOOR name.
    # Rebinding escalation.TIER3_FLOOR (in-process) must not lower the enforced
    # floor; the named constant is retained only for config-validation messaging.
    if score >= max(tier3, 30.0):
        return "tier3"
    if score >= tier2:
        return "tier2"
    if score >= tier1:
        return "tier1"
    return "none"


def evaluate_tier(score: float, config: PetasosConfig) -> str:
    if not math.isfinite(config.tier3_threshold) or config.tier3_threshold < TIER3_FLOOR:
        _logger.warning(
            "tier3_threshold %r is non-finite or below floor; returning tier3 fail-secure",
            config.tier3_threshold,
        )
        return "tier3"
    return derive_tier(
        score, config.tier1_threshold, config.tier2_threshold, config.tier3_threshold
    )


def evaluate_escalation(score: float, config: PetasosConfig) -> EscalationResult:
    tier = evaluate_tier(score, config)
    action = _TIER_ACTIONS[tier]
    if tier == "tier3":
        threshold_crossed = config.tier3_threshold
    elif tier == "tier2":
        threshold_crossed = config.tier2_threshold
    elif tier == "tier1":
        threshold_crossed = config.tier1_threshold
    else:
        threshold_crossed = None
    return EscalationResult(tier=tier, action=action, threshold_crossed=threshold_crossed)
