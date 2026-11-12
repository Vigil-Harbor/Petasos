"""Pin the termination floor against rebinding of exported constants."""

from __future__ import annotations

from typing import TYPE_CHECKING

import petasos.session.escalation as escalation
from petasos.session.escalation import derive_tier

if TYPE_CHECKING:
    import pytest


def test_tier3_floor_resists_module_rebind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(escalation, "TIER3_FLOOR", 5.0)
    assert derive_tier(29.0, 15.0, 20.0, 5.0) != "tier3"
    assert derive_tier(30.0, 15.0, 20.0, 5.0) == "tier3"


def test_tier3_floor_default_behavior() -> None:
    assert derive_tier(29.9, 15.0, 20.0, 25.0) != "tier3"
    assert derive_tier(30.0, 15.0, 20.0, 25.0) == "tier3"
