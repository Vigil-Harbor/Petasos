"""Config field metadata introspection for the console Config Editor."""

from __future__ import annotations

import dataclasses
import logging
import typing
from typing import Any, get_args, get_origin, get_type_hints

from petasos.config import _SECRET_FIELDS, PetasosConfig

_logger = logging.getLogger(__name__)

# Resolve stringified annotations to real types once
_RESOLVED_HINTS: dict[str, Any] = {}


def _get_hints() -> dict[str, Any]:
    if not _RESOLVED_HINTS:
        import collections.abc

        import petasos._types as _types_mod
        import petasos.config as _config_mod
        ns = {**vars(_types_mod), **vars(_config_mod), "Mapping": collections.abc.Mapping}
        try:
            _RESOLVED_HINTS.update(get_type_hints(PetasosConfig, globalns=ns))
        except Exception:
            _logger.warning("Failed to resolve type hints — falling back to field annotations")
            for f in dataclasses.fields(PetasosConfig):
                _RESOLVED_HINTS[f.name] = f.type
    return _RESOLVED_HINTS

_FIELD_META: dict[str, dict[str, Any]] = {
    "normalize_nfkc": {
        "description": "Apply Unicode NFKC normalization to collapse compatibility variants.",
        "section": "normalization",
    },
    "strip_zero_width": {
        "description": "Remove zero-width characters that can hide injections.",
        "section": "normalization",
    },
    "map_homoglyphs": {
        "description": "Map look-alike Unicode characters to their ASCII equivalents.",
        "section": "normalization",
    },
    "detect_rtl_override": {
        "description": "Detect and neutralize right-to-left override characters.",
        "section": "normalization",
    },
    "direction": {
        "description": (
            "Default scan direction: inbound (user to agent)"
            " or outbound (agent to user)."
        ),
        "section": "scanning",
    },
    "fail_mode": {
        "description": (
            "What happens if a scanner breaks: open = allow,"
            " closed = block, degraded = best-effort."
        ),
        "section": "fail_mode",
        "constraints": {"values": ["open", "closed", "degraded"]},
    },
    "scanner_timeout_seconds": {
        "description": "How long to wait for a scanner before giving up.",
        "section": "scanning",
        "constraints": {"min": 0.01, "max": 60},
    },
    "scanner_circuit_breaker_threshold": {
        "description": "Consecutive timeouts before a scanner is temporarily benched.",
        "section": "scanning",
        "constraints": {"min": 1},
    },
    "scanner_circuit_breaker_cooldown_seconds": {
        "description": "How long a benched scanner stays out before retrying.",
        "section": "scanning",
        "constraints": {"min": 0.01},
    },
    "anonymize": {
        "description": "Replace detected personal info with typed placeholders like [EMAIL].",
        "section": "anonymization",
    },
    "pii_entities": {
        "description": "Which PII entity types to detect (e.g., PERSON, EMAIL_ADDRESS).",
        "section": "anonymization",
    },
    "redaction_mode": {
        "description": "How to hide PII: redact, replace, hash, or mask.",
        "section": "anonymization",
        "constraints": {"values": ["redact", "replace", "hash", "mask"]},
    },
    "hash_key": {
        "description": "Secret key for hash-mode redaction. Never shown in full.",
        "section": "anonymization",
    },
    "frequency_enabled": {
        "description": "Track per-session frequency scores for risk assessment.",
        "section": "frequency",
    },
    "escalation_enabled": {
        "description": "Watch each conversation and tighten checks automatically as risk builds.",
        "section": "escalation",
    },
    "profile_name": {
        "description": "Active scanning profile (e.g., general, code_generation, admin).",
        "section": "profiles",
    },
    "tool_guard_enabled": {
        "description": "Intercept tool calls and scan parameters for injection payloads.",
        "section": "tool_guard",
    },
    "audit_enabled": {
        "description": "Emit audit events for every pipeline inspection.",
        "section": "audit",
    },
    "alert_enabled": {
        "description": "Evaluate alert rules and fire warnings on suspicious patterns.",
        "section": "alerting",
    },
    "alert_cooldown_seconds": {
        "description": "Minimum seconds between alerts of the same type.",
        "section": "alerting",
        "constraints": {"min": 0.01},
    },
    "alert_per_minute_cap": {
        "description": "Maximum alerts per minute across all rules.",
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_per_hour_cap": {
        "description": "Maximum alerts per hour across all rules.",
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_critical_per_minute_cap": {
        "description": "Maximum critical-severity alerts per minute.",
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_high_severity_threshold": {
        "description": "Minimum severity that triggers the high-severity alert rule.",
        "section": "alerting",
        "constraints": {"values": ["critical", "high", "medium", "low", "info"]},
    },
    "alert_rapid_fire_count": {
        "description": "Scan count that triggers the rapid-fire alert within the window.",
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_rapid_fire_window_seconds": {
        "description": "Time window for rapid-fire detection.",
        "section": "alerting",
        "constraints": {"min": 0.01},
    },
    "alert_cross_session_burst_count": {
        "description": "Session count that triggers the cross-session burst alert.",
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_cross_session_burst_window_seconds": {
        "description": "Time window for cross-session burst detection.",
        "section": "alerting",
        "constraints": {"min": 0.01},
    },
    "alert_pii_volume_threshold": {
        "description": "PII finding count that triggers the volume spike alert.",
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_pii_volume_window_seconds": {
        "description": "Time window for PII volume spike detection.",
        "section": "alerting",
        "constraints": {"min": 0.01},
    },
    "alert_ring_buffer_capacity": {
        "description": "Maximum number of recent alerts kept in memory.",
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_per_session_contribution_cap": {
        "description": "Max alerts one session can contribute per minute.",
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_max_session_contribution_entries": {
        "description": "Max per-session contribution tracker entries.",
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "audit_verbosity": {
        "description": "How much detail audit events carry: minimal, standard, or verbose.",
        "section": "audit",
        "constraints": {"values": ["minimal", "standard", "verbose"]},
    },
    "frequency_half_life_seconds": {
        "description": "How fast the frequency score decays when a session goes quiet.",
        "section": "frequency",
        "constraints": {"min": 0.01},
    },
    "frequency_weights": {
        "description": "Custom severity weights for frequency scoring (maps severity to weight).",
        "section": "frequency",
    },
    "rolling_window_seconds": {
        "description": "Time window for the rolling scan counter.",
        "section": "frequency",
        "constraints": {"min": 0.01},
    },
    "rolling_threshold": {
        "description": "Scan count in the rolling window that triggers an alert.",
        "section": "frequency",
        "constraints": {"min": 1},
    },
    "tier1_threshold": {
        "description": "Risk score that moves a conversation to tier 1 (light extra scrutiny).",
        "section": "escalation",
        "constraints": {"min": 0},
    },
    "tier2_threshold": {
        "description": "Risk score for tier 2 (closer watch). Must be higher than tier 1.",
        "section": "escalation",
        "constraints": {"min": 0},
    },
    "tier3_threshold": {
        "description": "Tier 3 is the strictest level. Always on — can't be set below 30.",
        "section": "escalation",
        "constraints": {"min": 30},
    },
    "max_sessions": {
        "description": "Maximum concurrent sessions tracked.",
        "section": "session",
        "constraints": {"min": 1},
    },
    "session_ttl_seconds": {
        "description": "How long an idle session lives before being cleaned up.",
        "section": "session",
        "constraints": {"min": 0.01},
    },
    "max_new_sessions_per_minute": {
        "description": "Rate limit on new session creation.",
        "section": "session",
        "constraints": {"min": 1},
    },
    "max_terminated_tombstones": {
        "description": "Maximum terminated session tombstones kept.",
        "section": "session",
        "constraints": {"min": 1},
    },
}

_EXCLUDED_FIELDS = frozenset({"session_secret"})


def _derive_type(annotation: Any) -> tuple[str, bool]:
    """Return (type_name, nullable) from a dataclass field annotation."""
    import types as _bt

    origin = get_origin(annotation)
    args = get_args(annotation)

    # Handle T | None — both typing.Union and types.UnionType (Python 3.10+)
    is_union = origin is typing.Union or isinstance(annotation, _bt.UnionType)
    if is_union:
        if not args:
            args = get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            inner_type, _ = _derive_type(non_none[0])
            return inner_type, True
        return "string", True

    if annotation is bool:
        return "boolean", False
    if annotation is float or annotation is int:
        return "number", False
    if annotation is str:
        return "string", False
    if annotation is bytes:
        return "bytes", False

    if origin is tuple:
        return "array", False

    # Literal types
    ann_str = str(annotation)
    if "Literal" in ann_str:
        return "enum", False

    # Mapping types
    origin_name = getattr(origin, "__name__", str(origin)) if origin else ""
    if "Mapping" in origin_name or "MappingProxyType" in origin_name:
        return "object", False
    if "Mapping" in ann_str:
        return "object", False

    return "string", False


def generate_config_metadata() -> list[dict[str, Any]]:
    """Produce field metadata for every PetasosConfig field (except excluded)."""
    hints = _get_hints()
    result: list[dict[str, Any]] = []
    for f in dataclasses.fields(PetasosConfig):
        if f.name in _EXCLUDED_FIELDS:
            continue

        meta = _FIELD_META.get(f.name)
        if meta is None:
            _logger.warning("Config field %r missing from metadata mapping — synthesizing", f.name)
            meta = {"description": "No description available.", "section": "unknown"}

        annotation = hints.get(f.name, f.type)
        type_name, nullable = _derive_type(annotation)
        entry: dict[str, Any] = {
            "name": f.name,
            "type": type_name,
            "nullable": nullable,
            "default": _serialize_default(f.default),
            "description": meta["description"],
            "section": meta["section"],
        }

        if f.name in _SECRET_FIELDS:
            entry["redacted"] = True

        if "constraints" in meta:
            entry["constraints"] = meta["constraints"]
        elif type_name == "enum":
            args = get_args(annotation)
            if not args:
                origin = get_origin(annotation)
                if origin is typing.Union:
                    for a in get_args(annotation):
                        if a is not type(None):
                            args = get_args(a)
                            break
            if args:
                entry["constraints"] = {"values": list(args)}

        result.append(entry)
    return result


def _serialize_default(val: Any) -> Any:
    if isinstance(val, tuple):
        return list(val)
    if val is dataclasses.MISSING:
        return None
    return val
