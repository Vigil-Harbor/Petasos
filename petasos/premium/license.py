from __future__ import annotations

import enum
import importlib.resources
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

_INVISIBLE_RE = re.compile(
    "[​‌‍⁠﻿ ]",
)


class LicenseState(enum.Enum):
    INACTIVE = "inactive"
    VALID = "valid"
    EXPIRED = "expired"
    INVALID = "invalid"


@dataclass(frozen=True)
class LicenseClaims:
    tier: str
    customer_id: str
    expiry: datetime
    issued_at: datetime
    features: frozenset[str]


class LicenseValidator:
    def __init__(self, *, clock_skew_seconds: float = 30.0) -> None:
        self._clock_skew = timedelta(seconds=clock_skew_seconds)
        self._key: Any = None
        try:
            pkg = importlib.resources.files("petasos.premium._keys")
            raw = pkg.joinpath("public.pem").read_bytes()
            from cryptography.hazmat.primitives.serialization import load_pem_public_key

            self._key = load_pem_public_key(raw)
        except Exception:
            self._key = None

    def validate(self, token: str) -> tuple[LicenseState, LicenseClaims | None]:
        if self._key is None:
            return (LicenseState.INVALID, None)

        cleaned = _INVISIBLE_RE.sub("", token.strip())
        if not cleaned:
            return (LicenseState.INVALID, None)

        try:
            payload: dict[str, Any] = jwt.decode(
                cleaned,
                self._key,
                algorithms=["EdDSA"],
                options={"require": ["exp", "iat"]},
                leeway=self._clock_skew,
            )
        except jwt.ExpiredSignatureError:
            return (LicenseState.EXPIRED, None)
        except Exception:
            return (LicenseState.INVALID, None)

        claims = LicenseClaims(
            tier=str(payload.get("tier", "standard")),
            customer_id=str(payload.get("customer_id", "")),
            expiry=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
            issued_at=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
            features=frozenset(payload.get("features", [])),
        )
        return (LicenseState.VALID, claims)


_DEFAULT_VALIDATOR: LicenseValidator | None = None


def validate_license(token: str) -> LicenseState:
    global _DEFAULT_VALIDATOR
    if _DEFAULT_VALIDATOR is None:
        _DEFAULT_VALIDATOR = LicenseValidator()
    state, _ = _DEFAULT_VALIDATOR.validate(token)
    return state
