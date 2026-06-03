"""PIPE-08 / PET-10: PETASOS_LICENSE_KEY env auto-activation trust boundary.

The process environment is part of the license trust boundary: a valid env key
sets license state to VALID at construction; an invalid one leaves license state
non-VALID. Feature availability is controlled by config toggles, not license
state. See Pipeline.activate() docstring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from petasos.config import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner
from petasos.session.license import LicenseState

if TYPE_CHECKING:
    import pytest

_ALL_FEATURES = ("frequency", "escalation", "tool_guard", "audit", "alerting")


def _all_features_config() -> PetasosConfig:
    return PetasosConfig(
        frequency_enabled=True,
        escalation_enabled=True,
        tool_guard_enabled=True,
        audit_enabled=True,
        alert_enabled=True,
    )


def test_valid_env_key_auto_activates(monkeypatch: pytest.MonkeyPatch, valid_token: str) -> None:
    # PET-10 (a): a valid env key auto-activates all features at construction.
    monkeypatch.setenv("PETASOS_LICENSE_KEY", valid_token)
    pipe = Pipeline([MinimalScanner()], config=_all_features_config())
    assert pipe._license_state == LicenseState.VALID
    for feature in _ALL_FEATURES:
        assert pipe.is_feature_enabled(feature) is True, f"expected {feature!r} to be active"


def test_invalid_env_key_does_not_gate_features(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PETASOS_LICENSE_KEY", "not-a-valid-jwt")
    pipe = Pipeline([MinimalScanner()], config=_all_features_config())
    assert pipe._license_state != LicenseState.VALID
    for feature in _ALL_FEATURES:
        assert pipe.is_feature_enabled(feature) is True


def test_no_env_key_features_still_active(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PETASOS_LICENSE_KEY", raising=False)
    pipe = Pipeline([MinimalScanner()], config=_all_features_config())
    assert pipe._license_state == LicenseState.INACTIVE
    for feature in _ALL_FEATURES:
        assert pipe.is_feature_enabled(feature) is True
