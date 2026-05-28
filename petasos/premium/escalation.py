from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from petasos.config import PetasosConfig

from petasos.config import TIER3_FLOOR as TIER3_FLOOR

_TIER_ACTIONS: dict[str, str] = {
    "none": "none",
    "tier1": "deep_inspect",
    "tier2": "enhanced_scrutiny",
    "tier3": "terminate",
}


@dataclass(frozen=True)
class EscalationResult:
    tier: str
    action: str
    threshold_crossed: float | None


def derive_tier(score: float, tier1: float, tier2: float, tier3: float) -> str:
    if not math.isfinite(score):
        return "tier3"
    if score >= max(tier3, TIER3_FLOOR):
        return "tier3"
    if score >= tier2:
        return "tier2"
    if score >= tier1:
        return "tier1"
    return "none"


def evaluate_tier(score: float, config: PetasosConfig) -> str:
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
