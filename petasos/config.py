from __future__ import annotations

import math
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

    from petasos._types import Direction

TIER3_FLOOR: Final[float] = 30.0

_BOOL_FIELDS: frozenset[str] = frozenset(
    {
        "normalize_nfkc",
        "strip_zero_width",
        "map_homoglyphs",
        "detect_rtl_override",
        "anonymize",
        "frequency_enabled",
        "escalation_enabled",
        "tool_guard_enabled",
        "audit_enabled",
        "alert_enabled",
    }
)


def _validate_tier_thresholds(tier1: float, tier2: float, tier3: float) -> None:
    if not all(math.isfinite(v) for v in (tier1, tier2, tier3)):
        raise ValueError(f"thresholds must be finite, got {tier1}, {tier2}, {tier3}")
    if not (tier1 < tier2 < tier3):
        raise ValueError(f"thresholds must be strictly ascending: {tier1} < {tier2} < {tier3}")
    if tier3 < TIER3_FLOOR:
        raise ValueError(f"tier3 must be >= {TIER3_FLOOR}, got {tier3}")


_SECRET_FIELDS: frozenset[str] = frozenset({"hash_key"})


@dataclass(frozen=True, slots=True)
class PetasosConfig:
    # Normalization toggles
    normalize_nfkc: bool = True
    strip_zero_width: bool = True
    map_homoglyphs: bool = True
    detect_rtl_override: bool = True

    # Scanning
    direction: Direction = "inbound"
    # open: ML failures ignored (pass-through)
    # degraded: partial or total ML failure → safe=False
    # closed: same as degraded + early-exit on CRITICAL from syntactic pre-filter
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

    # Alerting thresholds
    alert_cooldown_seconds: float = 60.0
    alert_per_minute_cap: int = 5
    alert_per_hour_cap: int = 20
    alert_critical_per_minute_cap: int = 20
    alert_high_severity_threshold: Literal["critical", "high", "medium", "low", "info"] = "high"
    alert_rapid_fire_count: int = 10
    alert_rapid_fire_window_seconds: float = 60.0
    alert_cross_session_burst_count: int = 3
    alert_cross_session_burst_window_seconds: float = 60.0
    alert_pii_volume_threshold: int = 20
    alert_pii_volume_window_seconds: float = 300.0
    alert_ring_buffer_capacity: int = 1000
    alert_per_session_contribution_cap: int = 2
    alert_max_session_contribution_entries: int = 10_000

    # Audit
    audit_verbosity: Literal["minimal", "standard", "verbose"] = "standard"

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
    max_terminated_tombstones: int = 10_000

    # Session token binding (FREQ-03 defense)
    session_secret: bytes | None = None

    def __post_init__(self) -> None:
        for fname in _BOOL_FIELDS:
            val = getattr(self, fname)
            if not isinstance(val, bool):
                raise TypeError(f"{fname} must be a bool, got {val!r}")
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
        if self.anonymize and self.redaction_mode == "hash" and not self.hash_key:
            raise ValueError(
                "hash_key is required and must be non-empty when "
                "redaction_mode='hash' and anonymize=True"
            )
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
        _validate_tier_thresholds(self.tier1_threshold, self.tier2_threshold, self.tier3_threshold)
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
        if (
            not isinstance(self.max_terminated_tombstones, int)
            or isinstance(self.max_terminated_tombstones, bool)
            or self.max_terminated_tombstones <= 0
        ):
            raise ValueError(
                f"max_terminated_tombstones must be a positive integer, "
                f"got {self.max_terminated_tombstones!r}"
            )
        if self.session_secret is not None and not isinstance(self.session_secret, bytes):
            raise ValueError(
                f"session_secret must be bytes or None, got {type(self.session_secret).__name__}"
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

        # Alerting field validation
        if self.alert_cooldown_seconds <= 0 or not math.isfinite(self.alert_cooldown_seconds):
            raise ValueError(
                f"alert_cooldown_seconds must be positive and finite, "
                f"got {self.alert_cooldown_seconds!r}"
            )
        if (
            not isinstance(self.alert_per_minute_cap, int)
            or isinstance(self.alert_per_minute_cap, bool)
            or self.alert_per_minute_cap <= 0
        ):
            raise ValueError(
                f"alert_per_minute_cap must be a positive integer, "
                f"got {self.alert_per_minute_cap!r}"
            )
        if (
            not isinstance(self.alert_per_hour_cap, int)
            or isinstance(self.alert_per_hour_cap, bool)
            or self.alert_per_hour_cap <= 0
        ):
            raise ValueError(
                f"alert_per_hour_cap must be a positive integer, got {self.alert_per_hour_cap!r}"
            )
        if (
            not isinstance(self.alert_critical_per_minute_cap, int)
            or isinstance(self.alert_critical_per_minute_cap, bool)
            or self.alert_critical_per_minute_cap <= 0
        ):
            raise ValueError(
                f"alert_critical_per_minute_cap must be a positive integer, "
                f"got {self.alert_critical_per_minute_cap!r}"
            )
        if self.alert_high_severity_threshold not in (
            "critical",
            "high",
            "medium",
            "low",
            "info",
        ):
            raise ValueError(
                f"alert_high_severity_threshold must be one of "
                f"'critical', 'high', 'medium', 'low', 'info', "
                f"got {self.alert_high_severity_threshold!r}"
            )
        if (
            not isinstance(self.alert_rapid_fire_count, int)
            or isinstance(self.alert_rapid_fire_count, bool)
            or self.alert_rapid_fire_count <= 0
        ):
            raise ValueError(
                f"alert_rapid_fire_count must be a positive integer, "
                f"got {self.alert_rapid_fire_count!r}"
            )
        if self.alert_rapid_fire_window_seconds <= 0 or not math.isfinite(
            self.alert_rapid_fire_window_seconds
        ):
            raise ValueError(
                f"alert_rapid_fire_window_seconds must be positive and finite, "
                f"got {self.alert_rapid_fire_window_seconds!r}"
            )
        if (
            not isinstance(self.alert_cross_session_burst_count, int)
            or isinstance(self.alert_cross_session_burst_count, bool)
            or self.alert_cross_session_burst_count <= 0
        ):
            raise ValueError(
                f"alert_cross_session_burst_count must be a positive integer, "
                f"got {self.alert_cross_session_burst_count!r}"
            )
        if self.alert_cross_session_burst_window_seconds <= 0 or not math.isfinite(
            self.alert_cross_session_burst_window_seconds
        ):
            raise ValueError(
                f"alert_cross_session_burst_window_seconds must be positive and finite, "
                f"got {self.alert_cross_session_burst_window_seconds!r}"
            )
        if (
            not isinstance(self.alert_pii_volume_threshold, int)
            or isinstance(self.alert_pii_volume_threshold, bool)
            or self.alert_pii_volume_threshold <= 0
        ):
            raise ValueError(
                f"alert_pii_volume_threshold must be a positive integer, "
                f"got {self.alert_pii_volume_threshold!r}"
            )
        if self.alert_pii_volume_window_seconds <= 0 or not math.isfinite(
            self.alert_pii_volume_window_seconds
        ):
            raise ValueError(
                f"alert_pii_volume_window_seconds must be positive and finite, "
                f"got {self.alert_pii_volume_window_seconds!r}"
            )
        if (
            not isinstance(self.alert_ring_buffer_capacity, int)
            or isinstance(self.alert_ring_buffer_capacity, bool)
            or self.alert_ring_buffer_capacity <= 0
        ):
            raise ValueError(
                f"alert_ring_buffer_capacity must be a positive integer, "
                f"got {self.alert_ring_buffer_capacity!r}"
            )
        if self.alert_rapid_fire_count > self.alert_ring_buffer_capacity:
            raise ValueError(
                f"alert_rapid_fire_count ({self.alert_rapid_fire_count}) must be "
                f"<= alert_ring_buffer_capacity ({self.alert_ring_buffer_capacity})"
            )
        if self.alert_cross_session_burst_count > self.alert_ring_buffer_capacity:
            raise ValueError(
                f"alert_cross_session_burst_count "
                f"({self.alert_cross_session_burst_count}) must be "
                f"<= alert_ring_buffer_capacity "
                f"({self.alert_ring_buffer_capacity})"
            )
        if (
            not isinstance(self.alert_per_session_contribution_cap, int)
            or isinstance(self.alert_per_session_contribution_cap, bool)
            or self.alert_per_session_contribution_cap <= 0
        ):
            raise ValueError(
                f"alert_per_session_contribution_cap must be a positive integer, "
                f"got {self.alert_per_session_contribution_cap!r}"
            )
        if (
            not isinstance(self.alert_max_session_contribution_entries, int)
            or isinstance(self.alert_max_session_contribution_entries, bool)
            or self.alert_max_session_contribution_entries <= 0
        ):
            raise ValueError(
                f"alert_max_session_contribution_entries must be a positive integer, "
                f"got {self.alert_max_session_contribution_entries!r}"
            )
        if self.alert_per_session_contribution_cap > self.alert_per_minute_cap:
            raise ValueError(
                f"alert_per_session_contribution_cap ({self.alert_per_session_contribution_cap}) "
                f"must be <= alert_per_minute_cap ({self.alert_per_minute_cap})"
            )
        if self.audit_verbosity not in ("minimal", "standard", "verbose"):
            raise ValueError(
                f"audit_verbosity must be 'minimal', 'standard', or 'verbose', "
                f"got {self.audit_verbosity!r}"
            )

    def to_dict(self, *, redact_secrets: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {}
        for f in fields(self):
            if f.name == "session_secret":
                continue
            val = getattr(self, f.name)
            if redact_secrets and f.name in _SECRET_FIELDS:
                d[f.name] = "[REDACTED]" if val is not None else None
                continue
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
        if "session_secret" in filtered and isinstance(filtered["session_secret"], str):
            import base64

            try:
                filtered["session_secret"] = base64.b64decode(filtered["session_secret"])
            except Exception:
                raise ValueError("session_secret must be valid base64") from None
        for key in _BOOL_FIELDS:
            if key in filtered and not isinstance(filtered[key], bool):
                raise TypeError(f"{key} must be a bool, got {filtered[key]!r}")
        return cls(**filtered)

    def copy(self) -> PetasosConfig:
        return self.from_dict(self.to_dict())
