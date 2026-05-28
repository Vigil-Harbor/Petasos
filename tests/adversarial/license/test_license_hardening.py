"""PET-39 regression: license hardening (LIC-04, LIC-07, LIC-08, LIC-09)."""

from __future__ import annotations

import importlib.resources
from datetime import datetime, timezone
from typing import Any

import jwt as pyjwt
import pytest

from petasos.premium.license import LicenseState, LicenseValidator
from tests.conftest import _PRIVATE_KEY, _make_token

# ---------------------------------------------------------------------------
# LIC-04: Key fingerprint pinning
# ---------------------------------------------------------------------------


def test_swapped_key_returns_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pem = b"-----BEGIN PUBLIC KEY-----\nTHISISNOTAREALKEY==\n-----END PUBLIC KEY-----\n"

    class _FakeTraversable:
        def read_bytes(self) -> bytes:
            return fake_pem

    class _FakePkg:
        def joinpath(self, _name: str) -> _FakeTraversable:
            return _FakeTraversable()

    monkeypatch.setattr(importlib.resources, "files", lambda _pkg: _FakePkg())
    v = LicenseValidator()
    state, claims = v.validate(_make_token())
    assert state == LicenseState.INVALID
    assert claims is None


def test_fingerprint_mismatch_nullifies_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_pem = b"-----BEGIN PUBLIC KEY-----\nTHISISNOTAREALKEY==\n-----END PUBLIC KEY-----\n"

    class _FakeTraversable:
        def read_bytes(self) -> bytes:
            return fake_pem

    class _FakePkg:
        def joinpath(self, _name: str) -> _FakeTraversable:
            return _FakeTraversable()

    monkeypatch.setattr(importlib.resources, "files", lambda _pkg: _FakePkg())
    v = LicenseValidator()
    assert v._key is None


def test_correct_fingerprint_loads_key() -> None:
    v = LicenseValidator()
    assert v._key is not None


# ---------------------------------------------------------------------------
# LIC-07: Claims construction overflow guard
# ---------------------------------------------------------------------------


def test_exp_overflow_returns_invalid() -> None:
    token = _make_token(extra_claims={"exp": 10**18})
    v = LicenseValidator()
    state, claims = v.validate(token)
    assert state == LicenseState.INVALID
    assert claims is None


def test_exp_infinity_returns_invalid() -> None:
    token = _make_token(extra_claims={"exp": float("inf")})
    v = LicenseValidator()
    state, claims = v.validate(token)
    assert state == LicenseState.INVALID
    assert claims is None


def test_iat_overflow_returns_invalid() -> None:
    now = datetime.now(tz=timezone.utc)
    payload: dict[str, Any] = {
        "sub": "petasos-license",
        "exp": now.timestamp() + 3600,
        "iat": 10**18,
        "tier": "pro",
        "customer_id": "cust-test",
        "features": [],
    }
    token = pyjwt.encode(payload, _PRIVATE_KEY, algorithm="EdDSA")
    v = LicenseValidator()
    state, claims = v.validate(token)
    assert state == LicenseState.INVALID
    assert claims is None


def test_malformed_features_returns_invalid() -> None:
    token = _make_token(extra_claims={"features": 42})
    v = LicenseValidator()
    state, claims = v.validate(token)
    assert state == LicenseState.INVALID
    assert claims is None


# ---------------------------------------------------------------------------
# LIC-08: Tier allowlist
# ---------------------------------------------------------------------------


def test_unknown_tier_returns_invalid() -> None:
    token = _make_token(tier="superadmin")
    v = LicenseValidator()
    state, claims = v.validate(token)
    assert state == LicenseState.INVALID
    assert claims is None


def test_null_tier_returns_invalid() -> None:
    token = _make_token(extra_claims={"tier": None})
    v = LicenseValidator()
    state, claims = v.validate(token)
    assert state == LicenseState.INVALID
    assert claims is None


def test_empty_tier_returns_invalid() -> None:
    token = _make_token(tier="")
    v = LicenseValidator()
    state, claims = v.validate(token)
    assert state == LicenseState.INVALID
    assert claims is None


@pytest.mark.parametrize("tier", ["free", "standard", "pro", "enterprise"])
def test_valid_tiers_accepted(tier: str) -> None:
    token = _make_token(tier=tier)
    v = LicenseValidator()
    state, claims = v.validate(token)
    assert state == LicenseState.VALID
    assert claims is not None
    assert claims.tier == tier


def test_missing_tier_defaults_to_standard() -> None:
    now = datetime.now(tz=timezone.utc)
    payload: dict[str, Any] = {
        "sub": "petasos-license",
        "exp": now.timestamp() + 3600,
        "iat": now.timestamp(),
        "customer_id": "cust-test",
        "features": [],
    }
    token = pyjwt.encode(payload, _PRIVATE_KEY, algorithm="EdDSA")
    v = LicenseValidator()
    state, claims = v.validate(token)
    assert state == LicenseState.VALID
    assert claims is not None
    assert claims.tier == "standard"


def test_custom_valid_tiers() -> None:
    custom = frozenset({"custom", "free", "standard", "pro", "enterprise"})
    v = LicenseValidator(valid_tiers=custom)
    token_custom = _make_token(tier="custom")
    state, claims = v.validate(token_custom)
    assert state == LicenseState.VALID
    assert claims is not None
    assert claims.tier == "custom"

    token_pro = _make_token(tier="pro")
    state, claims = v.validate(token_pro)
    assert state == LicenseState.VALID
    assert claims is not None


def test_custom_tiers_missing_builtins_rejected() -> None:
    with pytest.raises(ValueError, match="must include all built-in tiers"):
        LicenseValidator(valid_tiers=frozenset({"custom"}))


def test_empty_valid_tiers_rejected() -> None:
    with pytest.raises(ValueError, match="must include all built-in tiers"):
        LicenseValidator(valid_tiers=frozenset())


# ---------------------------------------------------------------------------
# LIC-09: Clock skew cap
# ---------------------------------------------------------------------------


def test_clock_skew_cap_exceeded() -> None:
    with pytest.raises(ValueError, match="<= 300"):
        LicenseValidator(clock_skew_seconds=301)


def test_clock_skew_cap_boundary() -> None:
    v = LicenseValidator(clock_skew_seconds=300)
    assert v._clock_skew.total_seconds() == 300


def test_clock_skew_negative() -> None:
    with pytest.raises(ValueError, match="finite non-negative"):
        LicenseValidator(clock_skew_seconds=-1)


def test_clock_skew_nan() -> None:
    with pytest.raises(ValueError, match="finite non-negative"):
        LicenseValidator(clock_skew_seconds=float("nan"))


def test_clock_skew_extreme() -> None:
    with pytest.raises(ValueError, match="<= 300"):
        LicenseValidator(clock_skew_seconds=1e9)
