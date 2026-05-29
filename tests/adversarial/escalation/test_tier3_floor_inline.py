"""PET-23 backfill: Tier-3 floor is an inline literal, immune to module rebinding."""

from __future__ import annotations

from typing import TYPE_CHECKING

import petasos.premium.escalation as escalation
from petasos.premium.escalation import derive_tier

if TYPE_CHECKING:
    import pytest


def test_tier3_floor_resists_module_rebind(monkeypatch: pytest.MonkeyPatch) -> None:
    # Attacker rebinds the module-level name to a low value (in-process).
    monkeypatch.setattr(escalation, "TIER3_FLOOR", 5.0)
    # derive_tier's floor is an inline 30.0 literal, so the rebind has no effect:
    # a score below 30 must NOT reach tier3 even with a low config tier3 arg.
    # (Pre-fix this used max(tier3, TIER3_FLOOR) and would return "tier3" here.)
    assert derive_tier(29.0, 15.0, 20.0, 5.0) != "tier3"
    # ...and the floor still holds at exactly 30 regardless of the low tier3 arg.
    assert derive_tier(30.0, 15.0, 20.0, 5.0) == "tier3"


def test_tier3_floor_default_behavior() -> None:
    # Sanity (no rebind): the inline floor pins tier3 at 30 even when the tier3
    # threshold arg is below the floor.
    assert derive_tier(29.9, 15.0, 20.0, 25.0) != "tier3"
    assert derive_tier(30.0, 15.0, 20.0, 25.0) == "tier3"
