from __future__ import annotations

import enum
import hashlib
import importlib.resources
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

_INVISIBLE_RE = re.compile(
    "[​‌‍⁠﻿ ]",
)


_EXPECTED_KEY_FINGERPRINT = "009e2106b18ccb31ac1d74da4db9a9dc35097cb378e1f84688ff1b350b1bfb92"

_VALID_TIERS: frozenset[str] = frozenset({"free", "standard", "pro", "enterprise"})


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
    def __init__(
        self,
        *,
        clock_skew_seconds: float = 30.0,
        valid_tiers: frozenset[str] | None = None,
    ) -> None:
        if not math.isfinite(clock_skew_seconds) or clock_skew_seconds < 0:
            raise ValueError(
                "clock_skew_seconds must be a finite non-negative number,"
                f" got {clock_skew_seconds}"
            )
        if clock_skew_seconds > 300:
            raise ValueError(f"clock_skew_seconds must be <= 300, got {clock_skew_seconds}")
        self._clock_skew = timedelta(seconds=clock_skew_seconds)
        if valid_tiers is not None and not _VALID_TIERS.issubset(valid_tiers):
            missing = _VALID_TIERS - valid_tiers
            raise ValueError(f"valid_tiers must include all built-in tiers, missing: {missing}")
        self._valid_tiers = frozenset(valid_tiers) if valid_tiers is not None else _VALID_TIERS
        self._key: Any = None
        try:
            pkg = importlib.resources.files("petasos.session._keys")
            raw = pkg.joinpath("public.pem").read_bytes()
            normalized = raw.replace(b"\r\n", b"\n")
            if hashlib.sha256(normalized).hexdigest() != _EXPECTED_KEY_FINGERPRINT:
                self._key = None
            else:
                from cryptography.hazmat.primitives.serialization import (
                    load_pem_public_key,
                )

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

        tier_str = str(payload.get("tier", "standard"))
        if tier_str not in self._valid_tiers:
            return (LicenseState.INVALID, None)

        try:
            claims = LicenseClaims(
                tier=tier_str,
                customer_id=str(payload.get("customer_id", "")),
                expiry=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
                issued_at=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
                features=frozenset(payload.get("features", [])),
            )
        except (OverflowError, OSError, ValueError, TypeError):
            return (LicenseState.INVALID, None)
        return (LicenseState.VALID, claims)


_DEFAULT_VALIDATOR: LicenseValidator | None = None


def validate_license(token: str) -> LicenseState:
    global _DEFAULT_VALIDATOR
    if _DEFAULT_VALIDATOR is None:
        _DEFAULT_VALIDATOR = LicenseValidator()
    state, _ = _DEFAULT_VALIDATOR.validate(token)
    return state
