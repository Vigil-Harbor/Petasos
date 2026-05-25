from __future__ import annotations

import math
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

    from petasos._types import Direction

_TIER3_FLOOR: float = 30.0


@dataclass(frozen=True)
class PetasosConfig:
    # Normalization toggles
    normalize_nfkc: bool = True
    strip_zero_width: bool = True
    map_homoglyphs: bool = True
    detect_rtl_override: bool = True

    # Scanning
    direction: Direction = "inbound"
    fail_mode: Literal["open", "closed", "degraded"] = "degraded"

    # Anonymization
    anonymize: bool = False
    pii_entities: tuple[str, ...] = ()
    redaction_mode: Literal["redact", "replace", "hash", "mask"] = "redact"
    hash_key: str | None = None

    # Premium feature toggles
    frequency_enabled: bool = False
    escalation_enabled: bool = False
    profile_name: str | None = None
    tool_guard_enabled: bool = False
    audit_enabled: bool = False
    alert_enabled: bool = False

    # Frequency tracking
    frequency_half_life_seconds: float = 60.0
    frequency_weights: Mapping[str, float] | None = None
    rolling_window_seconds: float = 300.0
    rolling_threshold: int = 10

    # Escalation thresholds
    tier1_threshold: float = 15.0
    tier2_threshold: float = 30.0
    tier3_threshold: float = 50.0

    # Session management
    max_sessions: int = 10_000
    session_ttl_seconds: float = 3600.0
    max_new_sessions_per_minute: int = 60

    def __post_init__(self) -> None:
        if not isinstance(self.pii_entities, tuple):
            object.__setattr__(self, "pii_entities", tuple(self.pii_entities))
        if self.direction not in ("inbound", "outbound"):
            raise ValueError(f"direction must be 'inbound' or 'outbound', got {self.direction!r}")
        if self.fail_mode not in ("open", "closed", "degraded"):
            raise ValueError(
                f"fail_mode must be 'open', 'closed', or 'degraded', got {self.fail_mode!r}"
            )
        if self.redaction_mode not in ("redact", "replace", "hash", "mask"):
            raise ValueError(
                f"redaction_mode must be 'redact', 'replace', 'hash', or 'mask', "
                f"got {self.redaction_mode!r}"
            )
        if self.anonymize and self.redaction_mode == "hash" and self.hash_key is None:
            raise ValueError("hash_key is required when redaction_mode='hash' and anonymize=True")
        for entity in self.pii_entities:
            if not isinstance(entity, str) or not entity:
                raise ValueError(f"pii_entities entries must be non-empty strings, got {entity!r}")

        # Premium field validation
        if self.frequency_half_life_seconds <= 0 or not math.isfinite(
            self.frequency_half_life_seconds
        ):
            raise ValueError(
                f"frequency_half_life_seconds must be positive and finite, "
                f"got {self.frequency_half_life_seconds!r}"
            )
        if self.rolling_window_seconds <= 0 or not math.isfinite(self.rolling_window_seconds):
            raise ValueError(
                f"rolling_window_seconds must be positive and finite, "
                f"got {self.rolling_window_seconds!r}"
            )
        if not isinstance(self.rolling_threshold, int) or self.rolling_threshold <= 0:
            raise ValueError(
                f"rolling_threshold must be a positive integer, got {self.rolling_threshold!r}"
            )
        for _tname, _tval in (
            ("tier1_threshold", self.tier1_threshold),
            ("tier2_threshold", self.tier2_threshold),
            ("tier3_threshold", self.tier3_threshold),
        ):
            if not math.isfinite(_tval):
                raise ValueError(f"{_tname} must be finite, got {_tval!r}")
        if not (self.tier1_threshold < self.tier2_threshold < self.tier3_threshold):
            raise ValueError(
                f"thresholds must be strictly ascending: "
                f"tier1={self.tier1_threshold} < tier2={self.tier2_threshold} "
                f"< tier3={self.tier3_threshold}"
            )
        if self.tier3_threshold < _TIER3_FLOOR:
            raise ValueError(
                f"tier3_threshold must be >= {_TIER3_FLOOR}, got {self.tier3_threshold}"
            )
        if not isinstance(self.max_sessions, int) or self.max_sessions <= 0:
            raise ValueError(f"max_sessions must be a positive integer, got {self.max_sessions!r}")
        if self.session_ttl_seconds <= 0 or not math.isfinite(self.session_ttl_seconds):
            raise ValueError(
                f"session_ttl_seconds must be positive and finite, "
                f"got {self.session_ttl_seconds!r}"
            )
        if (
            not isinstance(self.max_new_sessions_per_minute, int)
            or self.max_new_sessions_per_minute <= 0
        ):
            raise ValueError(
                f"max_new_sessions_per_minute must be a positive integer, "
                f"got {self.max_new_sessions_per_minute!r}"
            )
        if self.frequency_weights is not None:
            for k, v in self.frequency_weights.items():
                if not isinstance(k, str) or not k:
                    raise ValueError(
                        f"frequency_weights keys must be non-empty strings, got {k!r}"
                    )
                if v < 0 or not math.isfinite(v):
                    raise ValueError(
                        f"frequency_weights values must be non-negative and finite, "
                        f"got {k!r}: {v!r}"
                    )
            object.__setattr__(
                self, "frequency_weights", MappingProxyType(dict(self.frequency_weights))
            )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        for f in fields(self):
            val = getattr(self, f.name)
            if isinstance(val, tuple):
                val = list(val)
            elif isinstance(val, MappingProxyType):
                val = dict(val)
            d[f.name] = val
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PetasosConfig:
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        if "pii_entities" in filtered and isinstance(filtered["pii_entities"], list):
            filtered["pii_entities"] = tuple(filtered["pii_entities"])
        return cls(**filtered)

    def copy(self) -> PetasosConfig:
        return self.from_dict(self.to_dict())
