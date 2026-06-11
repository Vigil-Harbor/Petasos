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
        "help_plain": (
            "Rewrites stylized or alternate-form characters (like fullwidth letters) into"
            " plain standard text before scanning, so attacks dressed up in fancy lettering"
            " can't slip past. Turning this off also disables follow-up cleanup passes that"
            " depend on it, making evasion easier."
        ),
        "section": "normalization",
    },
    "strip_zero_width": {
        "description": "Remove zero-width characters that can hide injections.",
        "help_plain": (
            "Removes invisible characters that can be hidden inside text to smuggle"
            " instructions past the filters. Normal text looks exactly the same with this on"
            " — there's no reason to turn it off in everyday use."
        ),
        "section": "normalization",
    },
    "map_homoglyphs": {
        "description": "Map look-alike Unicode characters to their ASCII equivalents.",
        "help_plain": (
            'Catches text that uses look-alike letters (such as a Cyrillic "а" posing as'
            ' a Latin "a") to sneak past filters, by converting them to their plain'
            " equivalents. Turning this off makes scans slightly faster but easier to evade."
        ),
        "section": "normalization",
    },
    "detect_rtl_override": {
        "description": "Detect and neutralize right-to-left override characters.",
        "help_plain": (
            "Flags special characters that reverse the reading direction of text — a trick"
            " that disguises malicious content by displaying it backwards. This setting only"
            " raises the warning flag; actually removing those characters is handled by the"
            " invisible-character cleanup setting above (on by default)."
        ),
        "section": "normalization",
    },
    "direction": {
        "description": (
            "Default scan direction: inbound (user to agent) or outbound (agent to user)."
        ),
        "help_plain": (
            'Sets which way the text is flowing by default: "inbound" means messages coming'
            ' from the user to the agent, "outbound" means the'
            " agent's replies going out. Individual scanners may apply different checks"
            " depending on the direction."
        ),
        "section": "scanning",
    },
    "fail_mode": {
        "description": (
            "What happens if a scanner breaks: open = allow,"
            " closed = block, degraded = best-effort."
        ),
        "help_plain": (
            'Controls what happens when a scanner breaks mid-run: "open" lets content pass'
            ' anyway, while "degraded" (the default) and "closed" block it to stay safe.'
            ' "closed" is strictest — it also blocks immediately when the always-on pattern'
            " check finds something critical, without waiting for the other scanners."
        ),
        "section": "fail_mode",
        "constraints": {"values": ["open", "closed", "degraded"]},
    },
    "scanner_timeout_seconds": {
        "description": "How long to wait for a scanner before giving up.",
        "help_plain": (
            "How many seconds to wait for a slow scanner before giving up on it for that"
            " scan. Lower keeps scans snappy but cuts off slow scanners more often — and a"
            " timeout counts as a scanner failure, so the fail mode setting decides what"
            " happens next."
        ),
        "section": "scanning",
        "constraints": {"min": 0.01, "max": 60},
    },
    "scanner_circuit_breaker_threshold": {
        "description": "Consecutive timeouts before a scanner is temporarily benched.",
        "help_plain": (
            "How many times in a row a scanner must time out before it's temporarily"
            " benched so it stops slowing down every scan. Lower benches a misbehaving"
            " scanner sooner; any scan that doesn't time out resets the count."
        ),
        "section": "scanning",
        "constraints": {"min": 1},
    },
    "scanner_circuit_breaker_cooldown_seconds": {
        "description": "How long a benched scanner stays out before retrying.",
        "help_plain": (
            "How many seconds a benched scanner sits out before it gets another chance."
            " While benched it is skipped instantly but still counts as a failed scanner —"
            " so the fail mode setting decides whether content is blocked meanwhile; the"
            " built-in zero-dependency pattern check keeps running regardless."
        ),
        "section": "scanning",
        "constraints": {"min": 0.01},
    },
    "anonymize": {
        "description": "Replace detected personal info with typed placeholders like [EMAIL].",
        "help_plain": (
            "After scanning, replaces any personal information found (names, emails, and so"
            " on) with placeholders so it doesn't travel further. Off by default — turn it"
            " on when conversations may contain other people's data."
        ),
        "section": "anonymization",
    },
    "pii_entities": {
        "description": "Which PII entity types to detect (e.g., PERSON, EMAIL_ADDRESS).",
        "help_plain": (
            "Meant to list which kinds of personal information to look for (like PERSON or"
            " EMAIL_ADDRESS). Currently informational only — the personal-info scanner uses"
            " its own list, so changing this value has no effect yet."
        ),
        "section": "anonymization",
    },
    "redaction_mode": {
        "description": "How to hide PII: redact, replace, hash, or mask.",
        "help_plain": (
            'Chooses how found personal information is hidden: "redact" swaps it for a'
            ' typed placeholder, "replace" numbers each one, "hash" turns it into a'
            " scrambled code (useful for matching records without revealing them), and"
            ' "mask" hides all but the last few characters.'
        ),
        "section": "anonymization",
        "constraints": {"values": ["redact", "replace", "hash", "mask"]},
    },
    "hash_key": {
        "description": "Secret key for hash-mode redaction. Never shown in full.",
        "help_plain": (
            'The secret key used when redaction mode is "hash" — it makes the scrambled'
            " codes impossible to reverse without the key. Required for hash mode, ignored"
            " otherwise, and never displayed in full."
        ),
        "section": "anonymization",
    },
    "frequency_enabled": {
        "description": "Track per-session frequency scores for risk assessment.",
        "help_plain": (
            "Keeps a running risk score per conversation, so repeated suspicious behavior"
            " adds up instead of being judged one message at a time. Turning this off also"
            " stops the automatic escalation that depends on the score."
        ),
        "section": "frequency",
    },
    "escalation_enabled": {
        "description": "Watch each conversation and tighten checks automatically as risk builds.",
        "help_plain": (
            "Controls whether scan results report the conversation's escalation tier."
            " Turning it off does not relax enforcement — sessions still terminate at the"
            " top tier, the tool-call guard still blocks escalated conversations, and tier"
            " alerts still fire; a built-in emergency check can even still report the top"
            " tier on critical findings."
        ),
        "section": "escalation",
    },
    "profile_name": {
        "description": "Active scanning profile (e.g., general, code_generation, admin).",
        "help_plain": (
            'Picks a preset tuning bundle for a use case — built-ins are "general",'
            ' "customer_service", "code_generation", "research", and "admin" — each'
            " adjusting rule sensitivity, severity handling, and tool permissions. Leave"
            " unset to run without a profile."
        ),
        "section": "profiles",
    },
    "tool_guard_enabled": {
        "description": "Intercept tool calls and scan parameters for injection payloads.",
        "help_plain": (
            "Checks the agent's tool calls before they run, scanning their inputs for"
            " smuggled instructions and blocking calls from conversations that have"
            " escalated. Turning this off lets all tool calls through unchecked."
        ),
        "section": "tool_guard",
    },
    "audit_enabled": {
        "description": "Emit audit events for every pipeline inspection.",
        "help_plain": (
            "Records an audit event for every scan, so you can review afterwards what was"
            " checked and why decisions were made. Turning this off disables the activity"
            " feed and anything else built on audit events."
        ),
        "section": "audit",
    },
    "alert_enabled": {
        "description": "Evaluate alert rules and fire warnings on suspicious patterns.",
        "help_plain": (
            "Watches scan results for suspicious patterns — like rapid-fire scanning or a"
            " spike in detected personal information — and fires warnings when one appears."
            " Turning this off silences all alerts."
        ),
        "section": "alerting",
    },
    "alert_cooldown_seconds": {
        "description": "Minimum seconds between alerts of the same type.",
        "help_plain": (
            "Minimum quiet time, in seconds, before the same alert can fire again for the"
            " same conversation — stops one session repeating the same warning over and"
            " over. Critical alerts ignore this cooldown."
        ),
        "section": "alerting",
        "constraints": {"min": 0.01},
    },
    "alert_per_minute_cap": {
        "description": "Maximum alerts per minute across all rules.",
        "help_plain": (
            "The most alerts a single rule may fire per minute, counting all conversations"
            " together. Higher = noisier but less chance of missing something; critical"
            " alerts have their own separate cap."
        ),
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_per_hour_cap": {
        "description": "Maximum alerts per hour across all rules.",
        "help_plain": (
            "The most alerts a single rule may fire per hour — the long-term ceiling behind"
            " the per-minute cap. Lower keeps the alert feed quieter over sustained"
            " activity."
        ),
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_critical_per_minute_cap": {
        "description": "Maximum critical-severity alerts per minute.",
        "help_plain": (
            "A separate per-minute allowance just for critical alerts, which skip the"
            " normal limits so that emergencies always get through. This cap is the only"
            " bound on them."
        ),
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_high_severity_threshold": {
        "description": "Minimum severity that triggers the high-severity alert rule.",
        "help_plain": (
            'The minimum seriousness a finding needs to trigger the "high severity" alert.'
            ' Setting it lower (toward "info") fires alerts for almost everything; setting'
            ' it to "critical" alerts only on the worst findings.'
        ),
        "section": "alerting",
        "constraints": {"values": ["critical", "high", "medium", "low", "info"]},
    },
    "alert_rapid_fire_count": {
        "description": "Scan count that triggers the rapid-fire alert within the window.",
        "help_plain": (
            "How many scans from one conversation, inside the time window, count as a"
            " rapid-fire burst worth alerting on. Lower = more sensitive."
        ),
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_rapid_fire_window_seconds": {
        "description": "Time window for rapid-fire detection.",
        "help_plain": (
            "The time span, in seconds, over which one conversation's scans are counted for"
            " rapid-fire detection. A longer window also catches slower bursts."
        ),
        "section": "alerting",
        "constraints": {"min": 0.01},
    },
    "alert_cross_session_burst_count": {
        "description": "Session count that triggers the cross-session burst alert.",
        "help_plain": (
            "How many different conversations must show findings within the window before"
            " the coordinated-burst alert fires — a sign of an attack spread across"
            " sessions. Lower = more sensitive."
        ),
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_cross_session_burst_window_seconds": {
        "description": "Time window for cross-session burst detection.",
        "help_plain": (
            "The time span, in seconds, used to spot findings appearing across multiple"
            " conversations at once. Longer = catches slower coordinated activity."
        ),
        "section": "alerting",
        "constraints": {"min": 0.01},
    },
    "alert_pii_volume_threshold": {
        "description": "PII finding count that triggers the volume spike alert.",
        "help_plain": (
            "The total pieces of personal information detected within the window — across"
            " all conversations — that count as a leak spike worth alerting on. Lower ="
            " more sensitive."
        ),
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_pii_volume_window_seconds": {
        "description": "Time window for PII volume spike detection.",
        "help_plain": (
            "The time span, in seconds, over which detected personal information is"
            " totalled for the leak-spike alert. The default five minutes is long enough to"
            " catch slow leaks."
        ),
        "section": "alerting",
        "constraints": {"min": 0.01},
    },
    "alert_ring_buffer_capacity": {
        "description": "Maximum number of recent alerts kept in memory.",
        "help_plain": (
            "How many recent events the alert rules keep in memory for their counting."
            " Bigger remembers more history at the cost of memory — and the burst"
            " thresholds above must fit within it."
        ),
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_per_session_contribution_cap": {
        "description": "Max alerts one session can contribute per minute.",
        "help_plain": (
            "The most alerts any single conversation may contribute per rule per minute, so"
            " one noisy session can't use up the shared alert allowance and drown out"
            " everyone else. Must not exceed the per-minute cap."
        ),
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_max_session_contribution_entries": {
        "description": "Max per-session contribution tracker entries.",
        "help_plain": (
            "A memory-safety limit on how many conversation-and-rule combinations the alert"
            " fairness tracking can follow at once. Once full, alerts from brand-new"
            " combinations are dropped until stale entries expire."
        ),
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "audit_verbosity": {
        "description": "How much detail audit events carry: minimal, standard, or verbose.",
        "help_plain": (
            'How much detail each audit record carries: "minimal" is just the verdict and a'
            ' finding count, "standard" adds the findings and session risk details,'
            ' "verbose" adds full scanner output and a settings snapshot. More detail ='
            " better for debugging, more data stored."
        ),
        "section": "audit",
        "constraints": {"values": ["minimal", "standard", "verbose"]},
    },
    "frequency_half_life_seconds": {
        "description": "How fast the frequency score decays when a session goes quiet.",
        "help_plain": (
            "How quickly a conversation's risk score fades when things go quiet, in"
            " seconds: after this much idle time the score drops by half. Higher ="
            " suspicion is remembered longer."
        ),
        "section": "frequency",
        "constraints": {"min": 0.01},
    },
    "frequency_weights": {
        "description": "Custom severity weights for frequency scoring (maps severity to weight).",
        "help_plain": (
            "Fine-tunes how much different kinds of findings add to the risk score — for"
            " example, injection attempts can count more than odd encodings. Leave unset to"
            " use the built-in weights (an explicitly empty table is different: it stops"
            " findings from adding to the score at all)."
        ),
        "section": "frequency",
    },
    "rolling_window_seconds": {
        "description": "Time window for the rolling scan counter.",
        "help_plain": (
            "The recent time span, in seconds, over which flagged scans are counted per"
            " conversation. A bigger window catches slow, patient misbehavior; a smaller"
            " one reacts only to quick bursts."
        ),
        "section": "frequency",
        "constraints": {"min": 0.01},
    },
    "rolling_threshold": {
        "description": "Scan count in the rolling window that triggers an alert.",
        "help_plain": (
            "How many flagged scans within the window mark a conversation for extra"
            " scrutiny (escalation tier 1), even when each individual finding was minor."
            " Lower = more sensitive to slow-drip behavior."
        ),
        "section": "frequency",
        "constraints": {"min": 1},
    },
    "tier1_threshold": {
        "description": "Risk score that moves a conversation to tier 1 (light extra scrutiny).",
        "help_plain": (
            "Risk score at which a conversation gets light extra scrutiny — tool calls"
            " still work, but warnings are attached. Lower = stricter (reached sooner);"
            " must stay below the tier 2 threshold."
        ),
        "section": "escalation",
        "constraints": {"min": 0},
    },
    "tier2_threshold": {
        "description": "Risk score for tier 2 (closer watch). Must be higher than tier 1.",
        "help_plain": (
            "Risk score at which enforcement gets serious: tool calls are blocked except"
            " those explicitly exempted. Lower = stricter; must sit between the tier 1 and"
            " tier 3 thresholds."
        ),
        "section": "escalation",
        "constraints": {"min": 0},
    },
    "tier3_threshold": {
        "description": "Tier 3 is the strictest level. Always on — can't be set below 30.",
        "help_plain": (
            "Risk score at which the conversation is shut down — the session is terminated"
            " and stays terminated. Lower = stricter, but it can never take effect below"
            " the built-in floor of 30."
        ),
        "section": "escalation",
        "constraints": {"min": 30},
    },
    "max_sessions": {
        "description": "Maximum concurrent sessions tracked.",
        "help_plain": (
            "The most conversations tracked at once; when the limit is hit, the oldest"
            " finished-with sessions are dropped first to make room. During a flood of"
            " brand-new conversations while full, new ones may temporarily go untracked"
            " instead (see the per-minute limit below). Higher = more memory used."
        ),
        "section": "session",
        "constraints": {"min": 1},
    },
    "session_ttl_seconds": {
        "description": "How long an idle session lives before being cleaned up.",
        "help_plain": (
            "How long, in seconds, an idle conversation stays tracked before being cleaned"
            " up (default one hour). Cleanup happens opportunistically during later"
            " activity, not on an exact timer."
        ),
        "section": "session",
        "constraints": {"min": 0.01},
    },
    "max_new_sessions_per_minute": {
        "description": "Rate limit on new session creation.",
        "help_plain": (
            "Caps how many brand-new conversations may start per minute — but it only"
            " kicks in once the session store is already full. Protects against floods of"
            " throwaway sessions designed to overwhelm tracking."
        ),
        "section": "session",
        "constraints": {"min": 1},
    },
    "max_terminated_tombstones": {
        "description": "Maximum terminated session tombstones kept.",
        "help_plain": (
            "How many terminated conversations to remember by ID after they're cleaned"
            " away, so a banned session can't sneak back in under the same name. Higher ="
            " longer memory for slightly more storage."
        ),
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
            "help_plain": meta.get("help_plain") or meta["description"],
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
