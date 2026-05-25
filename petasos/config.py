from __future__ import annotations

import copy
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from petasos._types import Direction


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

    # Premium stubs (accepted but no runtime effect until PET-7+)
    frequency_enabled: bool = False
    escalation_enabled: bool = False
    profile_name: str | None = None
    tool_guard_enabled: bool = False
    audit_enabled: bool = False
    alert_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.pii_entities, tuple):
            object.__setattr__(self, "pii_entities", tuple(self.pii_entities))
        if self.direction not in ("inbound", "outbound"):
            raise ValueError(
                f"direction must be 'inbound' or 'outbound', got {self.direction!r}"
            )
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

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        for f in fields(self):
            val = getattr(self, f.name)
            if isinstance(val, tuple):
                val = list(val)
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
        return copy.deepcopy(self)
