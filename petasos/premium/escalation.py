from __future__ import annotations

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


def evaluate_tier(score: float, config: PetasosConfig) -> str:
    if score >= config.tier3_threshold:
        return "tier3"
    if score >= config.tier2_threshold:
        return "tier2"
    if score >= config.tier1_threshold:
        return "tier1"
    return "none"


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
