"""Config poisoning (PET-14 CFG-*)."""

from __future__ import annotations

import pytest

import petasos.config as config_mod
from petasos.config import PetasosConfig


def test_frozen_config_bypass_via_setattr() -> None:
    """CFG-01: object.__setattr__ mutates frozen instance."""
    cfg = PetasosConfig()
    object.__setattr__(cfg, "fail_mode", "open")
    assert cfg.fail_mode == "open"


def test_anonymize_truthy_non_bool_without_bool_check() -> None:
    """CFG-02: int 1 enables anonymize path without isinstance(bool) guard."""
    cfg = PetasosConfig(anonymize=1)  # type: ignore[arg-type]
    assert cfg.anonymize == 1
    assert bool(cfg.anonymize) is True


def test_tier3_floor_module_global_mutable() -> None:
    """CFG-04: reassigning TIER3_FLOOR lowers the enforced floor for new configs."""
    original = config_mod.TIER3_FLOOR
    try:
        config_mod.TIER3_FLOOR = 5.0
        cfg = PetasosConfig(tier1_threshold=1.0, tier2_threshold=2.0, tier3_threshold=10.0)
        assert cfg.tier3_threshold == 10.0  # rejected when TIER3_FLOOR is 30.0
    finally:
        config_mod.TIER3_FLOOR = original


def test_tier3_below_floor_rejected() -> None:
    """CFG-04: blocked-validated for config object path."""
    with pytest.raises(ValueError):
        PetasosConfig(tier3_threshold=10.0)
