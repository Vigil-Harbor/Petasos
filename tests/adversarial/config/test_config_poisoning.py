"""Config poisoning (PET-14 CFG-*)."""

from __future__ import annotations

import hashlib
import hmac

import pytest

import petasos.config.floors as floors
from petasos.config.schema import ConfigError, from_mapping
from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.model import ScanResult
from petasos.pipeline import Pipeline
from petasos.pipeline.findings import _compute_safe
from petasos.session.escalation import evaluate_tier


def test_frozen_config_bypass_via_setattr() -> None:
    """CFG-01: slots=True eliminates __dict__; object.__setattr__ on defined
    fields is an accepted Python-level residual (documented in D1)."""
    cfg = PetasosConfig()
    with pytest.raises(AttributeError):
        cfg.__dict__  # noqa: B018
    object.__setattr__(cfg, "fail_mode", "open")
    assert cfg.fail_mode == "open"


def _owned_escalation(tier3: float) -> PetasosConfig:
    """A config whose escalation section is not the shared default object."""
    cfg = from_mapping(
        PetasosConfig,
        {"escalation": {"tier1": 15.0, "tier2": 30.0, "tier3": 50.0}},
    )
    object.__setattr__(cfg.escalation, "tier3", tier3)
    return cfg


def test_tier3_floor_module_global_mutable(monkeypatch: pytest.MonkeyPatch) -> None:
    """CFG-04: rebinding the tier-3 floor constant does not open a hole.

    The bound is fixed when the section is declared, so a document under the
    floor is refused. Tampering a built value still fail-secures in
    evaluate_tier.
    """
    monkeypatch.setattr(floors, "TIER3_FLOOR", 5.0)
    with pytest.raises(ConfigError, match="escalation.tier3"):
        from_mapping(
            PetasosConfig,
            {"escalation": {"tier1": 1.0, "tier2": 2.0, "tier3": 10.0}},
        )
    assert evaluate_tier(0.0, _owned_escalation(10.0)) == "tier3"


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
    """CFG-04: evaluate_tier returns 'tier3' fail-secure when tier 3
    is tampered below 30.0."""
    assert evaluate_tier(0.0, _owned_escalation(5.0)) == "tier3"


def test_evaluate_tier_ignores_module_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rebinding the floor constant does not lower the tier evaluate_tier enforces."""
    monkeypatch.setattr(floors, "TIER3_FLOOR", 5.0)
    assert evaluate_tier(0.0, _owned_escalation(10.0)) == "tier3"


def test_pipeline_config_isolation() -> None:
    """The pipeline holds the tree it was given.

    The tree is frozen, so assignment does not change it. ``reconfigure``
    replaces the object and leaves the one the caller still holds alone.
    """
    cfg = PetasosConfig()
    pipeline = Pipeline(config=cfg)
    assert pipeline.config is cfg
    with pytest.raises(AttributeError):
        cfg.fail_mode = "open"  # type: ignore[misc]
    pipeline.reconfigure(PetasosConfig(fail_mode="open"))
    assert pipeline.config is not cfg
    assert pipeline.config.fail_mode == "open"
    assert cfg.fail_mode == "degraded"


def test_default_configs_share_no_nested_section() -> None:
    """Tampering with one default config's section reaches no other config."""
    first = PetasosConfig()
    second = PetasosConfig()
    assert first.escalation is not second.escalation
    object.__setattr__(first.escalation, "tier1", 49.0)
    assert second.escalation.tier1 == 15.0
    assert PetasosConfig().escalation.tier1 == 15.0


def test_pipeline_replace_preserves_session_secret() -> None:
    """CFG-05: reconfiguring the tree keeps the secret passed beside it."""
    secret = b"key"
    pipeline = Pipeline(
        config=PetasosConfig(), secrets=Secrets(session_secret=secret), host_id="h1"
    )
    pipeline.reconfigure(PetasosConfig(fail_mode="open"))
    tracker = pipeline._frequency_tracker
    assert tracker.requires_token is True
    token = tracker.mint_token("s1", "h1")
    expected = hmac.new(secret, b"s1\x00h1", hashlib.sha256).hexdigest()
    assert token.hmac_digest == expected


def test_compute_safe_fallback_on_invalid_fail_mode() -> None:
    """CFG-05: _compute_safe falls back to 'degraded' on invalid fail_mode,
    treating ML scanner errors as unsafe."""
    errored_ml = ScanResult(scanner_name="ml1", findings=(), duration_ms=0, error="fail")
    result = _compute_safe((), [errored_ml], "evil")
    assert result is False
