"""Config poisoning (PET-14 CFG-*)."""

from __future__ import annotations

import pytest

import petasos.config as config_mod
from petasos._types import ScanResult
from petasos.config import PetasosConfig
from petasos.pipeline import Pipeline, _compute_safe
from petasos.premium.escalation import evaluate_tier


def test_frozen_config_bypass_via_setattr() -> None:
    """CFG-01: slots=True eliminates __dict__; object.__setattr__ on defined
    fields is an accepted Python-level residual (documented in D1)."""
    cfg = PetasosConfig()
    with pytest.raises(AttributeError):
        cfg.__dict__  # noqa: B018
    object.__setattr__(cfg, "fail_mode", "open")
    assert cfg.fail_mode == "open"


def test_anonymize_truthy_non_bool_rejected() -> None:
    """CFG-02: int 1 for anonymize is now rejected by __post_init__."""
    with pytest.raises(TypeError, match="anonymize must be a bool"):
        PetasosConfig(anonymize=1)  # type: ignore[arg-type]


def test_tier3_floor_module_global_mutable(monkeypatch: pytest.MonkeyPatch) -> None:
    """CFG-04: reassigning TIER3_FLOOR lowers the construction floor, but
    evaluate_tier() catches it with an inline literal guard."""
    monkeypatch.setattr(config_mod, "TIER3_FLOOR", 5.0)
    cfg = PetasosConfig(tier1_threshold=1.0, tier2_threshold=2.0, tier3_threshold=10.0)
    assert cfg.tier3_threshold == 10.0
    assert evaluate_tier(0.0, cfg) == "tier3"


def test_tier3_below_floor_rejected() -> None:
    """CFG-04: blocked-validated for config object path."""
    with pytest.raises(ValueError):
        PetasosConfig(tier3_threshold=10.0)


# ---------------------------------------------------------------------------
# PET-23: Config immutability hardening tests
# ---------------------------------------------------------------------------


def test_slots_no_dict() -> None:
    """CFG-01: PetasosConfig has no __dict__ with slots=True."""
    cfg = PetasosConfig()
    assert not hasattr(cfg, "__dict__")


def test_slots_no_new_attr() -> None:
    """CFG-01: object.__setattr__ on undefined attributes raises AttributeError."""
    cfg = PetasosConfig()
    with pytest.raises(AttributeError):
        object.__setattr__(cfg, "evil", True)


def test_object_setattr_on_defined_field_residual() -> None:
    """CFG-01: object.__setattr__ on defined slot fields still works —
    accepted Python limitation, documented as residual in D1."""
    cfg = PetasosConfig()
    object.__setattr__(cfg, "fail_mode", "open")
    assert cfg.fail_mode == "open"


def test_evaluate_tier_failsecure_on_low_tier3() -> None:
    """CFG-04: evaluate_tier returns 'tier3' fail-secure when tier3_threshold
    is tampered below 30.0."""
    cfg = PetasosConfig()
    object.__setattr__(cfg, "tier3_threshold", 5.0)
    assert evaluate_tier(0.0, cfg) == "tier3"


def test_evaluate_tier_ignores_module_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    """CFG-04: mutating TIER3_FLOOR module variable does not bypass the inline
    literal guard in evaluate_tier()."""
    monkeypatch.setattr(config_mod, "TIER3_FLOOR", 5.0)
    cfg = PetasosConfig(tier1_threshold=1.0, tier2_threshold=2.0, tier3_threshold=10.0)
    assert evaluate_tier(0.0, cfg) == "tier3"


def test_pipeline_config_isolation() -> None:
    """CFG-05: mutating original config after Pipeline construction has no
    effect on pipeline's internal copy."""
    cfg = PetasosConfig()
    pipeline = Pipeline(config=cfg)
    object.__setattr__(cfg, "fail_mode", "open")
    assert pipeline.config.fail_mode == "degraded"


def test_pipeline_replace_preserves_session_secret() -> None:
    """CFG-05: dataclasses.replace() preserves session_secret without the
    object.__setattr__ workaround."""
    cfg = PetasosConfig(session_secret=b"key")
    pipeline = Pipeline(config=cfg, host_id="h1")
    assert pipeline.config.session_secret == b"key"


def test_compute_safe_fallback_on_invalid_fail_mode() -> None:
    """CFG-05: _compute_safe falls back to 'degraded' on invalid fail_mode,
    treating ML scanner errors as unsafe."""
    errored_ml = ScanResult(scanner_name="ml1", findings=(), duration_ms=0, error="fail")
    result = _compute_safe((), [errored_ml], "evil")
    assert result is False
