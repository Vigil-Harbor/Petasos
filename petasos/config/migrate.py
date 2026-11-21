"""One-shot read of a 0.5 flat ``petasos:`` section into a settings document.

The old name of every field lives in ``MOVES``. Migration and the parity tests
both read that table. Nothing here writes a secret into the result.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from petasos.config.layers import (
    LEVEL_FIELDS,
    LEVEL_NAMES,
    LEVELS,
    PROFILE_TO_ROLE,
    ROLES,
    contains,
)
from petasos.config.schema import ConfigError, FieldInfo, leaves, merge, to_mapping
from petasos.config.sections import PetasosConfig

_Kind = Literal["leaf", "role", "arm", "scanners", "drop"]

# Migration reports unavailable backends without rejecting the remaining settings.
_REMOVED_SCANNERS: dict[str, str] = {
    "llm_guard": "llm_guard was removed and was not copied.",
    "llama_firewall": "llama_firewall was removed and was not copied.",
}
_SCANNER_ENABLED: dict[str, str] = {
    "prompt_guard": "scanners.prompt_guard.enabled",
    "presidio": "scanners.presidio.enabled",
    "semgrep": "scanners.semgrep.enabled",
}
_ENTITY_EXTRA = "scanners.presidio.entities_extra"
_UPPER_PATHS = frozenset({"scanners.presidio.entities", _ENTITY_EXTRA})

# Profile tier values are migration diagnostics; escalation uses config thresholds.
_PROFILE_TIERS: dict[str, tuple[str, str, str]] = {
    "research": ("25, 45, 70", "relaxed", "25, 45, 65"),
    "admin": ("10, 20, 35", "strict", "10, 22, 40"),
}
_POSTURE = "tools.dangerous_posture"
# migrate_cmd recognises this note as an intentional blocking override.
_GENERAL_BLOCK_NOTE = (
    "The general role now asks a person before a risky tool call. "
    "This configuration was converted as general, whose old profile blocked "
    "those calls, so tools.dangerous_posture is set to block. "
    "The conversion does not start asking on its own."
)


@dataclass(frozen=True, slots=True)
class FieldMove:
    """Describe how a 0.5 field maps into settings or a dropped-field note.

    ``path`` is the new leaf, ``role``, or ``enabled``. It is None when the
    name is dropped. ``kind`` says which of those a caller is looking at.
    ``note`` is the sentence used when the name is dropped."""

    old: str
    path: str | None
    kind: _Kind = "leaf"
    note: str = ""


def _move(
    old: str,
    path: str | None,
    kind: _Kind = "leaf",
    note: str = "",
) -> FieldMove:
    return FieldMove(old=old, path=path, kind=kind, note=note)


MOVES: tuple[FieldMove, ...] = (
    _move("normalize_nfkc", "normalization.nfkc"),
    _move("strip_zero_width", "normalization.zero_width"),
    _move("map_homoglyphs", "normalization.homoglyphs"),
    _move("decode_encoded_payloads", "normalization.decode_payloads"),
    _move("direction", "direction"),
    _move("fail_mode", "fail_mode"),
    _move("scanner_timeout_seconds", "scanners.timeout_seconds"),
    _move("scanner_circuit_breaker_threshold", "scanners.breaker_threshold"),
    _move("scanner_circuit_breaker_cooldown_seconds", "scanners.breaker_cooldown_seconds"),
    _move("init_wait_timeout_seconds", "startup.wait_seconds"),
    _move("anonymize", "anonymization.enabled"),
    _move("pii_entities", "anonymization.entities"),
    _move("presidio_entities", "scanners.presidio.entities"),
    _move("presidio_entities_extra", _ENTITY_EXTRA),
    _move("presidio_score_threshold", "scanners.presidio.score_threshold"),
    _move("redaction_mode", "anonymization.mode"),
    _move("frequency_enabled", "frequency.enabled"),
    _move("escalation_enabled", "escalation.enabled"),
    _move("tool_guard_enabled", "tools.enabled"),
    _move("audit_enabled", "audit.enabled"),
    _move("alert_enabled", "alerting.enabled"),
    _move("alert_cooldown_seconds", "alerting.cooldown_seconds"),
    _move("alert_per_minute_cap", "alerting.per_minute_cap"),
    _move("alert_per_hour_cap", "alerting.per_hour_cap"),
    _move("alert_critical_per_minute_cap", "alerting.critical_per_minute_cap"),
    _move("alert_high_severity_threshold", "alerting.high_severity_threshold"),
    _move("alert_rapid_fire_count", "alerting.rapid_fire_count"),
    _move("alert_rapid_fire_window_seconds", "alerting.rapid_fire_window_seconds"),
    _move("alert_cross_session_burst_count", "alerting.cross_session_burst_count"),
    _move(
        "alert_cross_session_burst_window_seconds", "alerting.cross_session_burst_window_seconds"
    ),
    _move("alert_pii_volume_threshold", "alerting.pii_volume_threshold"),
    _move("alert_pii_volume_window_seconds", "alerting.pii_volume_window_seconds"),
    _move("alert_ring_buffer_capacity", "alerting.ring_buffer_capacity"),
    _move("alert_per_session_contribution_cap", "alerting.per_session_contribution_cap"),
    _move("alert_max_session_contribution_entries", "alerting.max_session_contribution_entries"),
    _move("audit_verbosity", "audit.verbosity"),
    _move("audit_emit_findings", "audit.emit_findings"),
    _move("frequency_half_life_seconds", "frequency.half_life_seconds"),
    _move("frequency_weights", "frequency.weights"),
    _move("rolling_window_seconds", "frequency.rolling_window_seconds"),
    _move("rolling_threshold", "frequency.rolling_threshold"),
    _move("tier1_threshold", "escalation.tier1"),
    _move("tier2_threshold", "escalation.tier2"),
    _move("tier3_threshold", "escalation.tier3"),
    _move("max_sessions", "sessions.max"),
    _move("session_ttl_seconds", "sessions.ttl_seconds"),
    _move("max_new_sessions_per_minute", "sessions.max_new_per_minute"),
    _move("max_terminated_tombstones", "sessions.max_tombstones"),
    _move("subagent_lineage_enabled", "tools.lineage.enabled"),
    _move("delegate_fanout_enabled", "tools.fanout.enabled"),
    _move("lineage_max_depth", "tools.lineage.max_depth"),
    _move("lineage_max_edges", "tools.lineage.max_edges"),
    _move("lineage_edge_ttl_seconds", "tools.lineage.edge_ttl_seconds"),
    _move("delegate_max_fanout_per_window", "tools.fanout.max_per_window"),
    _move("delegate_fanout_window_seconds", "tools.fanout.window_seconds"),
    _move("delegate_tool_names", "tools.delegate_names"),
    _move("egress_sink_tools", "egress.sink_tools"),
    _move("source_taint_namespaces", "egress.taint_namespaces"),
    _move("taint_min_span_length", "egress.taint_min_span_length"),
    _move("semgrep_engine_path", "scanners.semgrep.engine_path"),
    _move("semgrep_engine_sha256", "scanners.semgrep.engine_sha256"),
    _move("semgrep_request_timeout_seconds", "scanners.semgrep.request_timeout_seconds"),
    _move("semgrep_max_source_bytes", "scanners.semgrep.max_source_bytes"),
    _move("profile_name", "role", "role"),
    _move("dangerous_tool_posture", "tools.dangerous_posture"),
    _move("disabled_scanners", "scanners.<id>.enabled", "scanners"),
    _move("semgrep_enabled", "scanners.semgrep.enabled", "scanners"),
    _move("enabled", "enabled", "arm"),
    _move(
        "detect_rtl_override",
        None,
        "drop",
        "does not change a scan result, so it was removed",
    ),
    _move("fold_leet", None, "drop", "does not change a scan result, so it was removed"),
    _move(
        "session_secret",
        None,
        "drop",
        "is not a setting and was not copied. Set PETASOS_SESSION_SECRET in the environment.",
    ),
    _move(
        "hash_key",
        None,
        "drop",
        "is not a setting and was not copied. Set PETASOS_HASH_KEY in the environment.",
    ),
    _move(
        "host_id",
        None,
        "drop",
        "is not a setting. The host supplies it beside the config, and the value was not copied.",
    ),
)

_BY_OLD: dict[str, FieldMove] = {move.old: move for move in MOVES}
_INFO: dict[str, FieldInfo] = {info.path: info for info in leaves(PetasosConfig)}
_REVERSE: dict[str, str] = {
    move.path: move.old for move in MOVES if move.kind == "leaf" and move.path is not None
}


@dataclass(frozen=True, slots=True)
class Migration:
    """Hold converted settings and dropped-field notes without secret values.

    ``settings`` is a document ``resolve`` accepts. ``dropped`` names every key
    that was not copied, in the order it appeared. ``notes`` says why, in that
    same order, and never includes a secret value."""

    settings: Mapping[str, Any]
    dropped: tuple[str, ...]
    notes: tuple[str, ...]


def _get(doc: Mapping[str, Any], path: str) -> Any:
    node: object = doc
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            raise KeyError(path)
        node = node[part]
    return node


def _set(doc: dict[str, Any], path: str, value: object) -> None:
    parts = path.split(".")
    node = doc
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value


def _canon_strings(path: str, value: object) -> object:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        return value
    items: list[str] = []
    for item in value:
        if type(item) is not str:
            return value
        text = item.strip()
        if path in _UPPER_PATHS:
            text = text.upper()
        elif path == "tools.exempt":
            text = text.casefold()
        items.append(text)
    return items


def _canon_map(info: FieldInfo, value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    if info.type_name == "mapping[str, float]":
        numbers: dict[str, float] = {}
        for key, item in value.items():
            if type(key) is not str:
                return value
            if type(item) is int:
                numbers[key.strip()] = float(item)
            elif type(item) is float:
                numbers[key.strip()] = item
            else:
                return value
        return numbers
    texts: dict[str, str] = {}
    for key, item in value.items():
        if type(key) is not str or type(item) is not str:
            return value
        texts[key.strip()] = item.strip()
    return texts


def canon(info: FieldInfo, value: object) -> object:
    """Return the canonical schema value, retaining the input when invalid."""
    if value is None:
        return None
    if info.type_name == "float" and type(value) is int:
        return float(value)
    if info.type_name == "float" and type(value) is float:
        return value
    if info.type_name == "tuple[str, ...]":
        return _canon_strings(info.path, value)
    if info.type_name in ("mapping[str, float]", "mapping[str, str]"):
        return _canon_map(info, value)
    return value


def _defaults() -> dict[str, Any]:
    return to_mapping(PetasosConfig())


def _level_values(document: Mapping[str, Any]) -> dict[str, Any]:
    overlaid = merge(_defaults(), document)
    return {path: _get(overlaid, path) for path in sorted(LEVEL_FIELDS)}


def _user_level_values(section: Mapping[str, Any]) -> dict[str, Any]:
    defaults = _defaults()
    values: dict[str, Any] = {}
    for path in sorted(LEVEL_FIELDS):
        old = _REVERSE[path]
        if old in section:
            values[path] = canon(_INFO[path], section[old])
        else:
            values[path] = _get(defaults, path)
    return values


def _match_level(section: Mapping[str, Any]) -> str:
    user = _user_level_values(section)
    for name in LEVEL_NAMES:
        if user == _level_values(LEVELS[name].document):
            return name
    return "balanced"


def _role_entities(role_name: str) -> tuple[str, ...]:
    document = ROLES[role_name].document
    if not contains(document, _ENTITY_EXTRA):
        return ()
    value = _get(document, _ENTITY_EXTRA)
    if not isinstance(value, tuple):
        return ()
    return tuple(item for item in value if type(item) is str)


def _union_entities(flat: object, role_extra: tuple[str, ...]) -> object:
    """Config extras first, then profile extras that are not already listed.

    Both sources were additive at scan time. A replacing override would drop one.
    """
    canon_flat = _canon_strings(_ENTITY_EXTRA, flat)
    if not isinstance(canon_flat, list):
        return flat
    seen = set(canon_flat)
    for name in role_extra:
        if name not in seen:
            canon_flat.append(name)
            seen.add(name)
    return canon_flat


def _scanner_values(
    section: Mapping[str, Any],
    notes: list[str],
    dropped: list[str],
) -> dict[str, object]:
    values: dict[str, object] = {}
    disabled = section.get("disabled_scanners")
    if "disabled_scanners" in section:
        if isinstance(disabled, str) or not isinstance(disabled, (list, tuple)):
            notes.append("disabled_scanners must be a list of scanner ids and was not copied.")
            dropped.append("disabled_scanners")
        else:
            for scanner_id in disabled:
                if type(scanner_id) is not str:
                    notes.append("a non-text scanner id was not copied.")
                    continue
                removed = _REMOVED_SCANNERS.get(scanner_id)
                if removed is not None:
                    notes.append(removed)
                    continue
                path = _SCANNER_ENABLED.get(scanner_id)
                if path is None:
                    notes.append(f'unknown scanner id "{scanner_id}" was not copied.')
                    continue
                values[path] = "off"
    if "semgrep_enabled" in section:
        flag = section["semgrep_enabled"]
        path = _SCANNER_ENABLED["semgrep"]
        if flag is True and values.get(path) == "off":
            notes.append("semgrep was both enabled and listed as disabled; disabled wins.")
        elif flag is True:
            values[path] = "on"
        elif flag is False:
            values.setdefault(path, "off")
        else:
            values[path] = flag
    return values


def _explicit_leaves(
    section: Mapping[str, Any],
    role_name: str,
) -> dict[str, object]:
    leaves: dict[str, object] = {}
    for move in MOVES:
        if move.kind != "leaf" or move.path is None or move.old not in section:
            continue
        if move.path == _ENTITY_EXTRA:
            leaves[move.path] = _union_entities(section[move.old], _role_entities(role_name))
            continue
        info = _INFO.get(move.path)
        if info is None:
            continue
        leaves[move.path] = canon(info, section[move.old])
    return leaves


def _plain(value: object) -> object:
    """Lists and mappings, so a tuple from a frozen layer compares with a list."""
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items() if type(key) is str}
    return value


def _pin_general_block(
    role_name: str,
    section: Mapping[str, Any],
    leaves: dict[str, object],
    notes: list[str],
) -> None:
    """Keep a converted general profile blocking, unless it already names a posture."""
    if role_name != "general" or "dangerous_tool_posture" in section:
        return
    leaves[_POSTURE] = "block"
    notes.append(_GENERAL_BLOCK_NOTE)


def _overrides_for(base: Mapping[str, Any], leaves: Mapping[str, object]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for path, value in leaves.items():
        if _plain(value) != _plain(_get(base, path)):
            _set(overrides, path, _plain(value))
    return overrides


def _role_name(raw: object, notes: list[str], dropped: list[str]) -> str:
    if raw is None:
        return "general"
    if type(raw) is str:
        mapped = PROFILE_TO_ROLE.get(raw)
        if mapped is not None:
            return mapped
    dropped.append("profile_name")
    listed = ", ".join(PROFILE_TO_ROLE)
    notes.append(
        f'unknown profile "{raw}" was not copied. '
        f"Roles are {listed}. Put a custom profile's differences in overrides."
    )
    return "general"


def _tier_note(profile_name: object) -> str | None:
    if type(profile_name) is not str:
        return None
    detail = _PROFILE_TIERS.get(profile_name)
    if detail is None:
        return None
    old, suggested, numbers = detail
    return (
        f"The {profile_name} profile's escalation thresholds ({old}) were not applied "
        "by the Hermes plugin, because the guard was built without a profile, and they "
        f"are not part of the {PROFILE_TO_ROLE[profile_name]} role. The suggested level is "
        f"{suggested} ({numbers}). Choose that level, or set the escalation tiers in "
        "overrides, if you want thresholds in that neighborhood."
    )


def migrate(section: Mapping[str, Any]) -> Migration:
    """Read one flat ``petasos:`` section and return the equivalent settings.

    ``profile_name`` becomes ``role``. Level-owned fields that equal a level
    become that level; otherwise the level is ``balanced``. A value that still
    differs from what that role and level resolve to becomes an override.
    Unknown keys and secrets are reported and not copied.
    """
    if not isinstance(section, Mapping):
        raise ConfigError("a petasos section must be a group of named values")
    notes: list[str] = []
    dropped: list[str] = []
    for key in section:
        if type(key) is not str:
            notes.append("a non-text setting name was not copied.")
            continue
        move = _BY_OLD.get(key)
        if move is None:
            dropped.append(key)
            notes.append(f'unknown setting "{key}" was not copied.')
            continue
        if move.kind == "drop":
            dropped.append(key)
            notes.append(f"{key} {move.note}")

    role_name = "general"
    if "profile_name" in section and "profile_name" not in dropped:
        role_name = _role_name(section["profile_name"], notes, dropped)
    elif "profile_name" in section:
        role_name = "general"
    tier_note = _tier_note(section.get("profile_name"))
    if tier_note is not None and "profile_name" not in dropped:
        notes.append(tier_note)

    level_name = _match_level(section)
    enabled = section.get("enabled", True)
    leaves = _explicit_leaves(section, role_name)
    leaves.update(_scanner_values(section, notes, dropped))
    _pin_general_block(role_name, section, leaves, notes)
    # Disabled-scanner notes are about keys we did consume. Keep them, and do
    # not also list disabled_scanners as dropped.
    base = merge(_defaults(), ROLES[role_name].document)
    base = merge(base, LEVELS[level_name].document)
    overrides = _overrides_for(base, leaves)
    settings: dict[str, Any] = {
        "enabled": enabled,
        "role": role_name,
        "level": level_name,
        "overrides": overrides,
    }
    return Migration(settings=settings, dropped=tuple(dropped), notes=tuple(notes))
