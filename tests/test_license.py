from __future__ import annotations

from datetime import timedelta

import pytest

from petasos.premium.license import (
    LicenseState,
    LicenseValidator,
    validate_license,
)

from .conftest import _make_token


class TestLicenseValidator:
    def test_valid_token(self, valid_token: str) -> None:
        v = LicenseValidator()
        state, claims = v.validate(valid_token)
        assert state == LicenseState.VALID
        assert claims is not None
        assert claims.tier == "pro"
        assert claims.customer_id == "cust-test"

    def test_expired_token(self, expired_token: str) -> None:
        v = LicenseValidator()
        state, claims = v.validate(expired_token)
        assert state == LicenseState.EXPIRED
        assert claims is None

    def test_invalid_token_garbage(self) -> None:
        v = LicenseValidator()
        state, claims = v.validate("not-a-jwt")
        assert state == LicenseState.INVALID
        assert claims is None

    def test_empty_string(self) -> None:
        v = LicenseValidator()
        state, claims = v.validate("")
        assert state == LicenseState.INVALID
        assert claims is None

    def test_whitespace_only(self) -> None:
        v = LicenseValidator()
        state, claims = v.validate("   \t\n  ")
        assert state == LicenseState.INVALID
        assert claims is None

    def test_whitespace_stripping(self, valid_token: str) -> None:
        v = LicenseValidator()
        padded = f"  {valid_token}  \n"
        state, _ = v.validate(padded)
        assert state == LicenseState.VALID

    def test_bom_stripping(self, valid_token: str) -> None:
        v = LicenseValidator()
        bommed = f"﻿{valid_token}"
        state, _ = v.validate(bommed)
        assert state == LicenseState.VALID

    def test_zero_width_space_stripping(self, valid_token: str) -> None:
        v = LicenseValidator()
        zws = f"​{valid_token}​"
        state, _ = v.validate(zws)
        assert state == LicenseState.VALID

    def test_algorithm_restriction_hs256(self) -> None:
        import jwt as pyjwt

        token = pyjwt.encode(
            {"sub": "test", "exp": 9999999999, "iat": 1000000000},
            "this-is-a-test-key-with-32-bytes!",
            algorithm="HS256",
        )
        v = LicenseValidator()
        state, _ = v.validate(token)
        assert state == LicenseState.INVALID

    def test_claims_fields(self) -> None:
        token = _make_token(
            tier="enterprise",
            customer_id="acme-corp",
            features=["audit", "alerting"],
        )
        v = LicenseValidator()
        state, claims = v.validate(token)
        assert state == LicenseState.VALID
        assert claims is not None
        assert claims.tier == "enterprise"
        assert claims.customer_id == "acme-corp"
        assert claims.features == frozenset({"audit", "alerting"})
        assert claims.expiry.tzinfo is not None
        assert claims.issued_at.tzinfo is not None

    def test_default_tier_when_missing(self) -> None:
        token = _make_token(extra_claims={"tier": None})
        v = LicenseValidator()
        state, claims = v.validate(token)
        assert state == LicenseState.VALID
        assert claims is not None
        assert claims.tier == "None"

    def test_claims_frozen(self) -> None:
        token = _make_token()
        v = LicenseValidator()
        _, claims = v.validate(token)
        assert claims is not None
        with pytest.raises(AttributeError):
            claims.tier = "hacked"  # type: ignore[misc]

    def test_clock_skew_tolerance(self) -> None:
        token = _make_token(exp_delta=timedelta(seconds=-10))
        v = LicenseValidator(clock_skew_seconds=30.0)
        state, _ = v.validate(token)
        assert state == LicenseState.VALID

    def test_clock_skew_exceeded(self) -> None:
        token = _make_token(exp_delta=timedelta(seconds=-60))
        v = LicenseValidator(clock_skew_seconds=30.0)
        state, _ = v.validate(token)
        assert state == LicenseState.EXPIRED

    def test_missing_required_claims_exp(self) -> None:
        import jwt as pyjwt

        from tests.conftest import _PRIVATE_KEY

        payload = {"sub": "test", "iat": 1000000000}
        token = pyjwt.encode(payload, _PRIVATE_KEY, algorithm="EdDSA")
        v = LicenseValidator()
        state, _ = v.validate(token)
        assert state == LicenseState.INVALID

    def test_missing_required_claims_iat(self) -> None:
        import jwt as pyjwt

        from tests.conftest import _PRIVATE_KEY

        payload = {"sub": "test", "exp": 9999999999}
        token = pyjwt.encode(payload, _PRIVATE_KEY, algorithm="EdDSA")
        v = LicenseValidator()
        state, _ = v.validate(token)
        assert state == LicenseState.INVALID


class TestValidateLicenseConvenience:
    def test_valid(self, valid_token: str) -> None:
        assert validate_license(valid_token) == LicenseState.VALID

    def test_invalid(self) -> None:
        assert validate_license("garbage") == LicenseState.INVALID

    def test_expired(self, expired_token: str) -> None:
        assert validate_license(expired_token) == LicenseState.EXPIRED


class TestResilientKeyLoading:
    def test_missing_key_returns_invalid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import importlib.resources

        original_files = importlib.resources.files

        def _broken_files(pkg: str) -> object:
            if pkg == "petasos.premium._keys":
                raise FileNotFoundError("simulated missing package")
            return original_files(pkg)

        monkeypatch.setattr(importlib.resources, "files", _broken_files)
        v = LicenseValidator()
        assert v._key is None
        state, claims = v.validate(_make_token())
        assert state == LicenseState.INVALID
        assert claims is None
