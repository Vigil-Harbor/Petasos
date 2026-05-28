from __future__ import annotations

import importlib.resources
import json
import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from petasos._types import Severity
from petasos.config import _validate_tier_thresholds
from petasos.scanners.minimal import _ALL_INJECTION_IDS, _STRUCTURAL_RULE_IDS

_logger = logging.getLogger(__name__)

_UNSUPPRESSIBLE_RULE_IDS: frozenset[str] = _ALL_INJECTION_IDS | _STRUCTURAL_RULE_IDS


def _validate_suppress_rules(suppress: frozenset[str]) -> frozenset[str]:
    blocked = suppress & _UNSUPPRESSIBLE_RULE_IDS
    if blocked:
        _logger.warning(
            "suppress_rules attempted to suppress unsuppressible rules (stripped): %s",
            sorted(blocked),
        )
    return suppress - _UNSUPPRESSIBLE_RULE_IDS


@dataclass(frozen=True)
class TierThresholds:
    tier1: float
    tier2: float
    tier3: float

    def __post_init__(self) -> None:
        _validate_tier_thresholds(self.tier1, self.tier2, self.tier3)


@dataclass(frozen=True)
class ResolvedProfile:
    name: str
    suppress_rules: frozenset[str]
    severity_overrides: MappingProxyType[str, str]
    confidence_floor: float
    tier_thresholds: TierThresholds | None
    pii_entities_extra: tuple[str, ...]
    tool_exempt_list: frozenset[str]
    tool_alias_map: MappingProxyType[str, str]

    def __post_init__(self) -> None:
        cleaned = _validate_suppress_rules(self.suppress_rules)
        if cleaned != self.suppress_rules:
            object.__setattr__(self, "suppress_rules", cleaned)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "suppress_rules": sorted(self.suppress_rules),
            "severity_overrides": dict(self.severity_overrides),
            "confidence_floor": self.confidence_floor,
            "tier_thresholds": (
                {
                    "tier1": self.tier_thresholds.tier1,
                    "tier2": self.tier_thresholds.tier2,
                    "tier3": self.tier_thresholds.tier3,
                }
                if self.tier_thresholds is not None
                else None
            ),
            "pii_entities_extra": list(self.pii_entities_extra),
            "tool_exempt_list": sorted(self.tool_exempt_list),
            "tool_alias_map": dict(self.tool_alias_map),
        }


_BUILTIN_NAMES: tuple[str, ...] = (
    "general",
    "customer_service",
    "code_generation",
    "research",
    "admin",
)


def _check_structural_overrides(severity_overrides: dict[str, str]) -> None:
    structural = [k for k in severity_overrides if k in _STRUCTURAL_RULE_IDS]
    if structural:
        raise ValueError(
            f"severity_overrides cannot target structural rules: {sorted(structural)}"
        )


def _check_severity_values(severity_overrides: dict[str, str]) -> None:
    valid = {s.value for s in Severity}
    invalid = [f"{k}={v!r}" for k, v in severity_overrides.items() if v not in valid]
    if invalid:
        raise ValueError(f"invalid severity override values: {invalid}")


def _parse_profile(data: dict[str, Any]) -> ResolvedProfile:
    tt_raw = data.get("tier_thresholds")
    tier_thresholds: TierThresholds | None = None
    if tt_raw is not None:
        tier_thresholds = TierThresholds(
            tier1=float(tt_raw["tier1"]),
            tier2=float(tt_raw["tier2"]),
            tier3=float(tt_raw["tier3"]),
        )

    alias_map = data.get("tool_alias_map", {})
    for _k, v in alias_map.items():
        if not isinstance(v, str) or not v.strip():
            raise ValueError("tool_alias_map values must be non-empty strings")
    alias_map = {k: v.strip() for k, v in alias_map.items()}

    exempt_set = frozenset(s.strip().casefold() for s in data.get("tool_exempt_list", []))

    # GUARD-03: a profile alias may not target one of its own exempt keys
    collisions = {v.casefold() for v in alias_map.values()} & exempt_set
    if collisions:
        raise ValueError(
            f"profile {data.get('name', '?')!r}: tool_alias_map targets "
            f"cannot be exempt keys: {sorted(collisions)}"
        )

    sev_overrides = data.get("severity_overrides", {})
    _check_structural_overrides(sev_overrides)
    _check_severity_values(sev_overrides)

    return ResolvedProfile(
        name=data["name"],
        suppress_rules=_validate_suppress_rules(frozenset(data.get("suppress_rules", []))),
        severity_overrides=MappingProxyType(dict(sev_overrides)),
        confidence_floor=float(data.get("confidence_floor", 0.0)),
        tier_thresholds=tier_thresholds,
        pii_entities_extra=tuple(data.get("pii_entities_extra", [])),
        tool_exempt_list=exempt_set,
        tool_alias_map=MappingProxyType(dict(alias_map)),
    )


def _merge_with_base(
    base: ResolvedProfile,
    overrides: dict[str, Any],
) -> ResolvedProfile:
    suppress = base.suppress_rules
    if "suppress_rules" in overrides:
        val = overrides["suppress_rules"]
        if not isinstance(val, (list, set, frozenset)):
            raise ValueError("suppress_rules must be a list")
        suppress = _validate_suppress_rules(suppress | frozenset(val))

    severity = dict(base.severity_overrides)
    if "severity_overrides" in overrides:
        val = overrides["severity_overrides"]
        if not isinstance(val, dict):
            raise ValueError("severity_overrides must be a dict")
        severity.update(val)
    _check_structural_overrides(severity)
    _check_severity_values(severity)

    confidence = base.confidence_floor
    if "confidence_floor" in overrides:
        val = overrides["confidence_floor"]
        if not isinstance(val, (int, float)):
            raise ValueError("confidence_floor must be a number")
        confidence = float(val)

    tier_thresholds = base.tier_thresholds
    if "tier_thresholds" in overrides:
        val = overrides["tier_thresholds"]
        if val is None:
            tier_thresholds = None
        elif isinstance(val, dict):
            required = {"tier1", "tier2", "tier3"}
            if not required.issubset(val.keys()):
                raise ValueError("tier_thresholds requires all three keys: tier1, tier2, tier3")
            tier_thresholds = TierThresholds(
                tier1=float(val["tier1"]),
                tier2=float(val["tier2"]),
                tier3=float(val["tier3"]),
            )
        else:
            raise ValueError("tier_thresholds must be a dict or None")

    pii = base.pii_entities_extra
    if "pii_entities_extra" in overrides:
        val = overrides["pii_entities_extra"]
        if not isinstance(val, (list, tuple)):
            raise ValueError("pii_entities_extra must be a list")
        pii = tuple(set(pii) | set(val))

    exempt = base.tool_exempt_list
    if "tool_exempt_list" in overrides:
        val = overrides["tool_exempt_list"]
        if not isinstance(val, (list, set, frozenset)):
            raise ValueError("tool_exempt_list must be a list")
        exempt = frozenset(s.strip().casefold() for s in val)

    alias = dict(base.tool_alias_map)
    if "tool_alias_map" in overrides:
        val = overrides["tool_alias_map"]
        if not isinstance(val, dict):
            raise ValueError("tool_alias_map must be a dict")
        for _k, v in val.items():
            if not isinstance(v, str) or not v.strip():
                raise ValueError("tool_alias_map values must be non-empty strings")
        alias.update({k: v.strip() for k, v in val.items()})

    # GUARD-03: a profile alias may not target one of its own exempt keys
    collisions = {v.casefold() for v in alias.values()} & exempt
    if collisions:
        raise ValueError(
            f"profile 'custom': tool_alias_map targets cannot be exempt keys: {sorted(collisions)}"
        )

    return ResolvedProfile(
        name="custom",
        suppress_rules=suppress,
        severity_overrides=MappingProxyType(severity),
        confidence_floor=confidence,
        tier_thresholds=tier_thresholds,
        pii_entities_extra=pii,
        tool_exempt_list=exempt,
        tool_alias_map=MappingProxyType(alias),
    )


class ProfileResolver:
    def __init__(self) -> None:
        self._profiles: dict[str, ResolvedProfile] = {}
        self._load_builtins()

    def _load_builtins(self) -> None:
        pkg = importlib.resources.files("petasos.premium.profiles")
        for name in _BUILTIN_NAMES:
            traversable = pkg.joinpath(f"{name}.json")
            raw = traversable.read_text(encoding="utf-8")
            data = json.loads(raw)
            self._profiles[name] = _parse_profile(data)

    def resolve(self, name_or_dict: str | dict[str, Any]) -> ResolvedProfile:
        if isinstance(name_or_dict, str):
            try:
                return self._profiles[name_or_dict]
            except KeyError:
                raise KeyError(
                    f"Unknown profile '{name_or_dict}'. Available: {sorted(self._profiles.keys())}"
                ) from None
        if isinstance(name_or_dict, dict):
            base = self._profiles["general"]
            return _merge_with_base(base, name_or_dict)
        raise TypeError(f"name_or_dict must be str or dict, got {type(name_or_dict).__name__}")

    def register(self, name: str, profile: ResolvedProfile) -> None:
        self._profiles[name] = profile
