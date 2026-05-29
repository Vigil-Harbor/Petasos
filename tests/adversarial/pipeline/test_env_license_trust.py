"""PIPE-08 / PET-10: PETASOS_LICENSE_KEY env auto-activation trust boundary.

The process environment is part of the premium trust boundary: a valid env key
auto-activates premium at construction; an invalid one unlocks nothing and
leaves license state non-VALID. See Pipeline.activate() docstring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from petasos.config import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.premium.license import LicenseState
from petasos.scanners.minimal import MinimalScanner

if TYPE_CHECKING:
    import pytest

_ALL_FEATURES = ("frequency", "escalation", "tool_guard", "audit", "alerting")


def _all_premium_config() -> PetasosConfig:
    return PetasosConfig(
        frequency_enabled=True,
        escalation_enabled=True,
        tool_guard_enabled=True,
        audit_enabled=True,
        alert_enabled=True,
    )


def test_valid_env_key_auto_activates(monkeypatch: pytest.MonkeyPatch, valid_token: str) -> None:
    # PET-10 (a): a valid env key auto-activates premium at construction.
    monkeypatch.setenv("PETASOS_LICENSE_KEY", valid_token)
    pipe = Pipeline([MinimalScanner()], config=_all_premium_config())
    assert pipe._license_state == LicenseState.VALID
    assert pipe.is_premium_active("frequency") is True


def test_invalid_env_key_unlocks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    # PIPE-08 / PET-10 (b): an invalid env key unlocks no feature and leaves
    # state non-VALID.
    monkeypatch.setenv("PETASOS_LICENSE_KEY", "not-a-valid-jwt")
    pipe = Pipeline([MinimalScanner()], config=_all_premium_config())
    assert pipe._license_state != LicenseState.VALID
    for feature in _ALL_FEATURES:
        assert pipe.is_premium_active(feature) is False


def test_no_env_key_leaves_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PETASOS_LICENSE_KEY", raising=False)
    pipe = Pipeline([MinimalScanner()], config=_all_premium_config())
    assert pipe._license_state == LicenseState.INACTIVE
    for feature in _ALL_FEATURES:
        assert pipe.is_premium_active(feature) is False
