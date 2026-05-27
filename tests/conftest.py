from __future__ import annotations

import pathlib
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest

_FIXTURES = pathlib.Path(__file__).parent / "fixtures"
_PRIVATE_KEY = (_FIXTURES / "test_private.pem").read_bytes()


def _make_token(
    *,
    tier: str = "pro",
    customer_id: str = "cust-test",
    features: list[str] | None = None,
    exp_delta: timedelta = timedelta(hours=1),
    iat_delta: timedelta = timedelta(seconds=0),
    extra_claims: dict[str, object] | None = None,
    algorithm: str = "EdDSA",
    key: bytes | None = None,
) -> str:
    now = datetime.now(tz=timezone.utc)
    payload: dict[str, object] = {
        "sub": "petasos-license",
        "exp": now + exp_delta,
        "iat": now + iat_delta,
        "tier": tier,
        "customer_id": customer_id,
        "features": features or [],
    }
    if extra_claims:
        payload.update(extra_claims)
    return pyjwt.encode(payload, key or _PRIVATE_KEY, algorithm=algorithm)


@pytest.fixture()
def valid_token() -> str:
    return _make_token()


@pytest.fixture()
def expired_token() -> str:
    return _make_token(exp_delta=timedelta(hours=-1), iat_delta=timedelta(hours=-2))


@pytest.fixture()
def valid_key() -> str:
    return _make_token()
