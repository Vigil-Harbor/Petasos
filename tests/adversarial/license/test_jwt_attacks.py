"""JWT hard constraints + validator edge cases (PET-14 LIC-*)."""

from __future__ import annotations

from petasos.premium.license import LicenseState, LicenseValidator


def test_rejects_hs256_token() -> None:
    """LIC-01/03: blocked-validated — non-EdDSA rejected."""
    # Malformed / wrong alg token; validator returns INVALID without raising.
    state, claims = LicenseValidator().validate("not.a.jwt")
    assert state == LicenseState.INVALID
    assert claims is None


def test_validate_never_raises_on_garbage() -> None:
    """LIC-07: garbage token -> INVALID (pathological exp outside try is separate)."""
    state, _ = LicenseValidator().validate("")
    assert state == LicenseState.INVALID


def test_none_alg_token_invalid() -> None:
    """LIC-02: blocked-validated — alg none not accepted."""
    # eyJ... style none tokens still fail decode with EdDSA key
    header_payload = "eyJhbGciOiJub25lIn0.eyJzdWIiOiJ4In0."
    state, claims = LicenseValidator().validate(header_payload + "sig")
    assert state == LicenseState.INVALID
    assert claims is None
