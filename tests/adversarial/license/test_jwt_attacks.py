"""JWT hard constraints + validator edge cases (PET-14 LIC-*)."""

from __future__ import annotations

import jwt

from petasos.premium.license import LicenseState, LicenseValidator

_CLAIMS = {"exp": 9999999999, "iat": 1, "tier": "admin"}
_HS256_KEY = "x" * 48  # >= 32 bytes to avoid pyjwt's InsecureKeyLengthWarning


def test_rejects_hs256_token() -> None:
    """LIC-01/03: a syntactically valid HS256 token (key-confusion attempt) is rejected.

    The validator pins algorithms=["EdDSA"], so an HMAC-signed token cannot be
    verified against the bundled Ed25519 public key.
    """
    token = jwt.encode(_CLAIMS, _HS256_KEY, algorithm="HS256")
    state, claims = LicenseValidator().validate(token)
    assert state == LicenseState.INVALID
    assert claims is None


def test_none_alg_token_invalid() -> None:
    """LIC-02: a syntactically valid alg:none token is rejected."""
    token = jwt.encode(_CLAIMS, None, algorithm="none")  # type: ignore[arg-type]
    state, claims = LicenseValidator().validate(token)
    assert state == LicenseState.INVALID
    assert claims is None


def test_validate_never_raises_on_garbage() -> None:
    """LIC-07: empty / malformed / invisible-only tokens -> INVALID without raising."""
    for bad in ("", "not.a.jwt", chr(0x200B) + chr(0x200B)):
        state, claims = LicenseValidator().validate(bad)
        assert state == LicenseState.INVALID
        assert claims is None
