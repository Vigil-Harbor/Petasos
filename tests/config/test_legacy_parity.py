"""Equality with the 0.5 config, profiles, and strength presets.

This module is deleted at the cutover, along with the flat config it compares
against. The new tree is also tested on its own in the neighbouring files.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import fields
from typing import Any

import pytest

from petasos.config import TIER3_FLOOR as OLD_TIER3_FLOOR
from petasos.config import PetasosConfig as OldConfig
from petasos.config.floors import (
    INJECTION_PREFIX,
    KNOWN_PII_ENTITIES,
    PRESIDIO_LANGUAGE,
    PRESIDIO_SCORE_THRESHOLD,
    PROMPT_GUARD_THRESHOLD,
    SELFMOD_BASE_SEVERITY,
    SELFMOD_PREFIX,
    STRUCTURAL_PREFIX,
    TIER3_FLOOR,
)
from petasos.config.layers import PROFILE_TO_ROLE, ROLES, resolve
from petasos.config.migrate import MOVES, Migration, canon, migrate
from petasos.config.schema import ConfigError, FieldInfo, describe, from_mapping, to_mapping
from petasos.config.sections import PetasosConfig
from petasos.console._presets import _PRESET_REGISTRY
from petasos.scanners.minimal import (
    _ALL_INJECTION_IDS,
    _STRUCTURAL_RULE_IDS,
    RULE_TAXONOMY,
)
from petasos.scanners.presidio import KNOWN_PII_ENTITIES as SCANNER_PII_ENTITIES
from petasos.scanners.presidio import PresidioScanner
from petasos.scanners.prompt_guard import _BLOCK_THRESHOLD
from petasos.session.profiles import ProfileResolver, _parse_profile

_INFO = {row.path: row for row in describe(PetasosConfig)}
_BY_OLD = {move.old: move for move in MOVES}
_LEAF = {move.old: move.path for move in MOVES if move.kind == "leaf" and move.path is not None}
_PRESET_LEVEL = {"bronze": "relaxed", "iron": "balanced", "steel": "strict"}
_LEVEL_OWNED_OLD = {
    old: path
    for old, path in _LEAF.items()
    if path
    in {
        "fail_mode",
        "escalation.tier1",
        "escalation.tier2",
        "escalation.tier3",
        "scanners.presidio.score_threshold",
        "anonymization.enabled",
    }
}


def _get(document: Mapping[str, Any], path: str) -> Any:
    node: object = document
    for part in path.split("."):
        assert isinstance(node, Mapping)
        node = node[part]
    return node


def _same(old: object, new: object) -> bool:
    if isinstance(old, tuple):
        old = list(old)
    if isinstance(new, tuple):
        new = list(new)
    if isinstance(old, Mapping):
        old = dict(old)
    if isinstance(new, Mapping):
        new = dict(new)
    return old == new


def _union(flat: object, extra: tuple[str, ...]) -> object:
    info = _INFO["scanners.presidio.entities_extra"]
    values = canon(info, list(flat) if isinstance(flat, tuple) else flat)
    if not isinstance(values, list):
        return flat
    seen = set(values)
    for name in extra:
        if name not in seen:
            values.append(name)
            seen.add(name)
    return values


def _role_entities(role_name: str) -> tuple[str, ...]:
    document = ROLES[role_name].document
    node: object = document
    for part in ("scanners", "presidio", "entities_extra"):
        if not isinstance(node, Mapping) or part not in node:
            return ()
        node = node[part]
    if not isinstance(node, tuple):
        return ()
    return tuple(item for item in node if type(item) is str)


def _expected_enabled(section: Mapping[str, Any], scanner: str) -> str:
    disabled = section.get("disabled_scanners", ())
    if isinstance(disabled, (list, tuple)) and scanner in disabled:
        return "off"
    if scanner == "semgrep" and section.get("semgrep_enabled") is True:
        return "on"
    if scanner == "semgrep":
        return "off"
    return "auto"


def test_every_old_field_is_mapped_or_dropped() -> None:
    old_names = {item.name for item in fields(OldConfig)}
    accounted = {move.old for move in MOVES}

    assert old_names <= accounted
    dropped = {move.old for move in MOVES if move.kind == "drop"}
    assert dropped & old_names == {
        "detect_rtl_override",
        "fold_leet",
        "session_secret",
        "hash_key",
    }
    assert old_names - dropped - set(_LEAF) == {
        "profile_name",
        "disabled_scanners",
        "semgrep_enabled",
    }


def test_mapped_defaults_equal_the_old_defaults() -> None:
    old = OldConfig()
    new = to_mapping(PetasosConfig())

    for old_name, path in _LEAF.items():
        assert path is not None
        assert _same(getattr(old, old_name), _get(new, path)), old_name


def test_prefixes_select_the_scanner_sets() -> None:
    structural = {rule_id for rule_id in RULE_TAXONOMY if rule_id.startswith(STRUCTURAL_PREFIX)}
    injection = {rule_id for rule_id in RULE_TAXONOMY if rule_id.startswith(INJECTION_PREFIX)}

    assert structural == set(_STRUCTURAL_RULE_IDS)
    assert injection == set(_ALL_INJECTION_IDS)
    assert not any(rule_id.startswith(SELFMOD_PREFIX) for rule_id in RULE_TAXONOMY)
    assert all(rule_id.startswith(SELFMOD_PREFIX) for rule_id in SELFMOD_BASE_SEVERITY)


def test_stated_constants_match_the_scanner_and_the_old_floor() -> None:
    signature = inspect.signature(PresidioScanner.__init__)

    assert TIER3_FLOOR == OLD_TIER3_FLOOR
    assert PROMPT_GUARD_THRESHOLD == _BLOCK_THRESHOLD
    assert signature.parameters["language"].default == PRESIDIO_LANGUAGE
    assert signature.parameters["score_threshold"].default == PRESIDIO_SCORE_THRESHOLD
    assert KNOWN_PII_ENTITIES == SCANNER_PII_ENTITIES


@pytest.mark.parametrize("profile_name", sorted(PROFILE_TO_ROLE))
def test_role_levers_match_the_profile(profile_name: str) -> None:
    profile = ProfileResolver().resolve(profile_name)
    role_name = PROFILE_TO_ROLE[profile_name]
    config = resolve({"role": role_name, "level": "balanced"}).config

    assert set(config.rules.suppress) == set(profile.suppress_rules)
    assert dict(config.rules.severity_overrides) == dict(profile.severity_overrides)
    assert config.rules.confidence_floor == profile.confidence_floor
    assert config.rules.injection_floor_scope == profile.injection_floor_scope
    assert config.tools.dangerous_posture == profile.dangerous_tool_posture
    assert config.scanners.presidio.entities_extra == profile.pii_entities_extra
    assert config.tools.exempt == ()
    assert dict(config.tools.aliases) == {}


def test_research_and_admin_tiers_are_the_only_profile_difference() -> None:
    research = ProfileResolver().resolve("research")
    admin = ProfileResolver().resolve("admin")
    assert research.tier_thresholds is not None
    assert admin.tier_thresholds is not None
    assert (
        research.tier_thresholds.tier1,
        research.tier_thresholds.tier2,
        research.tier_thresholds.tier3,
    ) == (25, 45, 70)
    assert (
        admin.tier_thresholds.tier1,
        admin.tier_thresholds.tier2,
        admin.tier_thresholds.tier3,
    ) == (
        10,
        20,
        35,
    )

    suggested = resolve({"role": "research", "level": ROLES["research"].suggests}).config
    strict = resolve({"role": "admin", "level": ROLES["admin"].suggests}).config
    assert (
        suggested.escalation.tier1,
        suggested.escalation.tier2,
        suggested.escalation.tier3,
    ) == (
        25.0,
        45.0,
        65.0,
    )
    assert (strict.escalation.tier1, strict.escalation.tier2, strict.escalation.tier3) == (
        10.0,
        22.0,
        40.0,
    )
    for name in ("general", "code_generation", "customer_service"):
        assert ProfileResolver().resolve(name).tier_thresholds is None


@pytest.mark.parametrize("preset_key,level_name", sorted(_PRESET_LEVEL.items()))
def test_level_matches_the_preset_on_its_fields(preset_key: str, level_name: str) -> None:
    preset = next(item for item in _PRESET_REGISTRY if item.key == preset_key)
    mapped = to_mapping(resolve({"level": level_name}).config)

    for old_name, path in _LEVEL_OWNED_OLD.items():
        assert _same(preset.overrides[old_name], _get(mapped, path))
    assert to_mapping(resolve({"level": "balanced"}).config) == to_mapping(PetasosConfig())


def _migrated_equals(section: dict[str, Any]) -> None:
    old = OldConfig.from_dict(dict(section))
    result: Migration = migrate(section)
    new = to_mapping(resolve(result.settings).config)
    role_name = result.settings["role"]
    for old_name, path in _LEAF.items():
        assert path is not None
        expected = getattr(old, old_name)
        if path == "scanners.presidio.entities_extra":
            expected = _union(expected, _role_entities(str(role_name)))
        info: FieldInfo = _INFO[path]
        assert _same(canon(info, expected), _get(new, path)), old_name
    for scanner in ("prompt_guard", "presidio", "semgrep"):
        assert new["scanners"][scanner]["enabled"] == _expected_enabled(section, scanner)


def test_migrating_spread_matches_the_old_config() -> None:
    sections: list[dict[str, Any]] = [{}]
    sections.extend({"profile_name": name} for name in PROFILE_TO_ROLE)
    for preset in _PRESET_REGISTRY:
        if preset.key in _PRESET_LEVEL:
            sections.append(dict(preset.overrides))
    sections.append(
        {
            "profile_name": "admin",
            "fail_mode": "open",
            "tier1_threshold": 12,
            "normalize_nfkc": False,
            "presidio_entities_extra": ["url"],
            "delegate_tool_names": ["delegate_task", "spawn"],
            "alert_per_minute_cap": 8,
            "disabled_scanners": ["presidio"],
            "semgrep_enabled": True,
            "frequency_weights": {"petasos.syntactic.command.*": 3},
        }
    )
    sections.append({"disabled_scanners": ["prompt_guard", "semgrep"], "semgrep_enabled": True})

    for section in sections:
        _migrated_equals(section)


def test_three_presets_migrate_without_overrides() -> None:
    for preset in _PRESET_REGISTRY:
        if preset.key not in _PRESET_LEVEL:
            continue
        result = migrate(dict(preset.overrides))
        assert result.settings["level"] == _PRESET_LEVEL[preset.key]
        assert result.settings["overrides"] == {}


@pytest.mark.parametrize(
    ("old", "new_document", "path"),
    [
        (
            {"semgrep_engine_path": "rel"},
            {"scanners": {"semgrep": {"engine_path": "rel"}}},
            "engine_path",
        ),
        (
            {"semgrep_engine_sha256": "zz"},
            {"scanners": {"semgrep": {"engine_sha256": "zz"}}},
            "engine_sha256",
        ),
        (
            {"semgrep_request_timeout_seconds": 9},
            {"scanners": {"semgrep": {"request_timeout_seconds": 9}}},
            "request_timeout_seconds",
        ),
        (
            {"semgrep_max_source_bytes": 10},
            {"scanners": {"semgrep": {"max_source_bytes": 10}}},
            "max_source_bytes",
        ),
        ({"anonymize": 1}, {"anonymization": {"enabled": 1}}, "enabled"),
        ({"direction": "sideways"}, {"direction": "sideways"}, "direction"),
        ({"fail_mode": "maybe"}, {"fail_mode": "maybe"}, "fail_mode"),
        ({"redaction_mode": "blur"}, {"anonymization": {"mode": "blur"}}, "mode"),
        ({"pii_entities": [" "]}, {"anonymization": {"entities": [" "]}}, "entities"),
        (
            {"presidio_entities": "EMAIL"},
            {"scanners": {"presidio": {"entities": "EMAIL"}}},
            "entities",
        ),
        ({"presidio_entities": []}, {"scanners": {"presidio": {"entities": []}}}, "entities"),
        (
            {"presidio_entities_extra": "URL"},
            {"scanners": {"presidio": {"entities_extra": "URL"}}},
            "entities_extra",
        ),
        (
            {"presidio_score_threshold": 2},
            {"scanners": {"presidio": {"score_threshold": 2}}},
            "score_threshold",
        ),
        ({"scanner_timeout_seconds": 0}, {"scanners": {"timeout_seconds": 0}}, "timeout_seconds"),
        (
            {"scanner_timeout_seconds": 61},
            {"scanners": {"timeout_seconds": 61}},
            "timeout_seconds",
        ),
        ({"init_wait_timeout_seconds": -1}, {"startup": {"wait_seconds": -1}}, "wait_seconds"),
        (
            {"scanner_circuit_breaker_threshold": 0},
            {"scanners": {"breaker_threshold": 0}},
            "breaker_threshold",
        ),
        (
            {"scanner_circuit_breaker_threshold": True},
            {"scanners": {"breaker_threshold": True}},
            "breaker_threshold",
        ),
        (
            {"scanner_circuit_breaker_cooldown_seconds": 0},
            {"scanners": {"breaker_cooldown_seconds": 0}},
            "breaker_cooldown_seconds",
        ),
        (
            {"frequency_half_life_seconds": 0},
            {"frequency": {"half_life_seconds": 0}},
            "half_life_seconds",
        ),
        (
            {"rolling_window_seconds": 0},
            {"frequency": {"rolling_window_seconds": 0}},
            "rolling_window",
        ),
        ({"rolling_threshold": 0}, {"frequency": {"rolling_threshold": 0}}, "rolling_threshold"),
        (
            {"tier1_threshold": 40, "tier2_threshold": 30, "tier3_threshold": 50},
            {"escalation": {"tier1": 40, "tier2": 30, "tier3": 50}},
            "escalation",
        ),
        ({"tier3_threshold": 10}, {"escalation": {"tier3": 10}}, "tier3"),
        (
            {"tier1_threshold": float("nan"), "tier2_threshold": 30, "tier3_threshold": 50},
            {"escalation": {"tier1": float("nan"), "tier2": 30, "tier3": 50}},
            "tier1",
        ),
        ({"max_sessions": 0}, {"sessions": {"max": 0}}, "max"),
        ({"session_ttl_seconds": 0}, {"sessions": {"ttl_seconds": 0}}, "ttl_seconds"),
        (
            {"max_new_sessions_per_minute": 0},
            {"sessions": {"max_new_per_minute": 0}},
            "max_new_per_minute",
        ),
        (
            {"max_terminated_tombstones": True},
            {"sessions": {"max_tombstones": True}},
            "max_tombstones",
        ),
        ({"lineage_max_depth": 0}, {"tools": {"lineage": {"max_depth": 0}}}, "max_depth"),
        ({"lineage_max_edges": 0}, {"tools": {"lineage": {"max_edges": 0}}}, "max_edges"),
        (
            {"lineage_edge_ttl_seconds": 0},
            {"tools": {"lineage": {"edge_ttl_seconds": 0}}},
            "edge_ttl_seconds",
        ),
        (
            {"delegate_max_fanout_per_window": 0},
            {"tools": {"fanout": {"max_per_window": 0}}},
            "max_per_window",
        ),
        (
            {"delegate_fanout_window_seconds": 0},
            {"tools": {"fanout": {"window_seconds": 0}}},
            "window_seconds",
        ),
        (
            {"delegate_tool_names": "delegate_task"},
            {"tools": {"delegate_names": "delegate_task"}},
            "delegate_names",
        ),
        (
            {"egress_sink_tools": "send_email"},
            {"egress": {"sink_tools": "send_email"}},
            "sink_tools",
        ),
        (
            {"source_taint_namespaces": "mcp_bank_"},
            {"egress": {"taint_namespaces": "mcp_bank_"}},
            "taint_namespaces",
        ),
        (
            {"taint_min_span_length": 0},
            {"egress": {"taint_min_span_length": 0}},
            "taint_min_span_length",
        ),
        ({"frequency_weights": {"x": -1}}, {"frequency": {"weights": {"x": -1}}}, "weights"),
        ({"frequency_weights": {"": 1}}, {"frequency": {"weights": {"": 1}}}, "weights"),
        ({"alert_cooldown_seconds": 0}, {"alerting": {"cooldown_seconds": 0}}, "cooldown_seconds"),
        ({"alert_per_minute_cap": True}, {"alerting": {"per_minute_cap": True}}, "per_minute_cap"),
        (
            {"alert_high_severity_threshold": "severe"},
            {"alerting": {"high_severity_threshold": "severe"}},
            "high_severity_threshold",
        ),
        ({"alert_rapid_fire_count": 0}, {"alerting": {"rapid_fire_count": 0}}, "rapid_fire_count"),
        (
            {"alert_rapid_fire_window_seconds": 0},
            {"alerting": {"rapid_fire_window_seconds": 0}},
            "rapid_fire_window_seconds",
        ),
        (
            {"alert_cross_session_burst_count": 0},
            {"alerting": {"cross_session_burst_count": 0}},
            "cross_session_burst_count",
        ),
        (
            {"alert_cross_session_burst_window_seconds": 0},
            {"alerting": {"cross_session_burst_window_seconds": 0}},
            "cross_session_burst_window_seconds",
        ),
        (
            {"alert_pii_volume_threshold": 0},
            {"alerting": {"pii_volume_threshold": 0}},
            "pii_volume_threshold",
        ),
        (
            {"alert_pii_volume_window_seconds": 0},
            {"alerting": {"pii_volume_window_seconds": 0}},
            "pii_volume_window_seconds",
        ),
        (
            {"alert_ring_buffer_capacity": 0},
            {"alerting": {"ring_buffer_capacity": 0}},
            "ring_buffer_capacity",
        ),
        (
            {"alert_rapid_fire_count": 1001},
            {"alerting": {"rapid_fire_count": 1001}},
            "rapid_fire_count",
        ),
        (
            {"alert_cross_session_burst_count": 1001},
            {"alerting": {"cross_session_burst_count": 1001}},
            "cross_session_burst_count",
        ),
        (
            {"alert_per_session_contribution_cap": 6},
            {"alerting": {"per_session_contribution_cap": 6}},
            "per_session_contribution_cap",
        ),
        (
            {"alert_max_session_contribution_entries": 0},
            {"alerting": {"max_session_contribution_entries": 0}},
            "max_session_contribution_entries",
        ),
        ({"audit_verbosity": "debug"}, {"audit": {"verbosity": "debug"}}, "verbosity"),
        (
            {"disabled_scanners": "presidio"},
            {"scanners": {"presidio": {"enabled": "presidio"}}},
            "enabled",
        ),
        (
            {"disabled_scanners": ["nope"]},
            {"scanners": {"prompt_guard": {"enabled": "yes"}}},
            "enabled",
        ),
    ],
)
def test_old_invalid_value_is_rejected(
    old: dict[str, Any], new_document: dict[str, Any], path: str
) -> None:
    with pytest.raises((ValueError, TypeError)):
        OldConfig.from_dict(old)
    with pytest.raises(ConfigError) as caught:
        from_mapping(PetasosConfig, new_document)
    assert any(
        item == path or item.endswith(path) or path in item for item, _ in caught.value.errors
    )


def test_repaired_suppressions_are_now_errors() -> None:
    structural = "petasos.syntactic.structural.oversized-payload"
    selfmod = "petasos.selfmod.config_write"
    injection = "petasos.syntactic.injection.ignore-previous"
    stripped = ProfileResolver().resolve(
        {"suppress_rules": [structural, selfmod, injection], "injection_floor_scope": "all"}
    )
    kept = ProfileResolver().resolve(
        {"suppress_rules": [injection], "injection_floor_scope": "inbound"}
    )

    assert structural not in stripped.suppress_rules
    assert selfmod not in stripped.suppress_rules
    assert injection not in stripped.suppress_rules
    assert injection in kept.suppress_rules
    with pytest.raises(ConfigError):
        from_mapping(PetasosConfig, {"rules": {"suppress": [structural]}})
    with pytest.raises(ConfigError):
        from_mapping(PetasosConfig, {"rules": {"suppress": [selfmod]}})
    with pytest.raises(ConfigError):
        from_mapping(PetasosConfig, {"rules": {"suppress": [injection]}})
    accepted = from_mapping(
        PetasosConfig,
        {"rules": {"suppress": [injection], "injection_floor_scope": "inbound"}},
    )
    assert accepted.rules.suppress == (injection,)


def test_profile_shape_rules_are_rejected() -> None:
    with pytest.raises(ValueError):
        ProfileResolver().resolve({"dangerous_tool_posture": "allow"})
    with pytest.raises(ValueError):
        ProfileResolver().resolve({"injection_floor_scope": "outbound"})
    with pytest.raises(ValueError):
        ProfileResolver().resolve(
            {"severity_overrides": {"petasos.syntactic.structural.oversized-payload": "low"}}
        )
    with pytest.raises(ValueError):
        ProfileResolver().resolve({"tool_alias_map": {"shell": "  "}})
    with pytest.raises(ValueError):
        ProfileResolver().resolve(
            {"tool_exempt_list": ["exec"], "tool_alias_map": {"shell": "exec"}}
        )
    data = ProfileResolver().resolve("admin").to_dict()
    data["pii_entities_extra"] = ["NOT_A_TYPE"]
    with pytest.raises(ValueError):
        _parse_profile(data)

    for document in (
        {"tools": {"dangerous_posture": "allow"}},
        {"rules": {"injection_floor_scope": "outbound"}},
        {
            "rules": {
                "severity_overrides": {"petasos.syntactic.structural.oversized-payload": "low"}
            }
        },
        {"tools": {"aliases": {"shell": "  "}}},
        {"tools": {"exempt": ["exec"], "aliases": {"shell": "exec"}}},
        {"scanners": {"presidio": {"entities_extra": ["NOT_A_TYPE"]}}},
    ):
        with pytest.raises(ConfigError):
            from_mapping(PetasosConfig, document)


def test_hash_mode_without_a_key_moved_out_of_config() -> None:
    with pytest.raises(ValueError):
        OldConfig.from_dict({"anonymize": True, "redaction_mode": "hash"})

    config = from_mapping(PetasosConfig, {"anonymization": {"enabled": True, "mode": "hash"}})
    assert config.anonymization.enabled is True


@pytest.mark.anyio
async def test_selfmod_base_severities_match_the_guard(tmp_path: Any) -> None:
    import os
    import time

    from petasos._types import Severity
    from petasos.pipeline import Pipeline
    from petasos.session.frequency import FrequencyTracker
    from petasos.session.guard import ToolCallGuard

    owned = tmp_path / "profiles" / "gibson" / "config.yaml"
    owned.parent.mkdir(parents=True)
    owned.touch()
    owned_text = os.path.normcase(str(owned.resolve(strict=False)))
    old = OldConfig()
    pipeline = Pipeline(config=old)
    tracker = FrequencyTracker(old)
    guard = ToolCallGuard(pipeline, tracker, old)
    guard._selfmod_owned_cache = (time.monotonic() + 9999, frozenset({owned_text}))

    write = await guard.evaluate("write_file", {"path": owned_text, "content": "x"}, "s1")
    mention = await guard.evaluate(
        "write_file", {"path": "notes.md", "content": f"see {owned_text}"}, "s1"
    )
    assert write.selfmod_finding is not None
    assert mention.selfmod_finding is not None
    assert (
        SELFMOD_BASE_SEVERITY["petasos.selfmod.config_write"]
        == write.selfmod_finding.severity.value
    )
    assert write.selfmod_finding.severity is Severity.CRITICAL
    assert (
        SELFMOD_BASE_SEVERITY["petasos.selfmod.config_ref"]
        == mention.selfmod_finding.severity.value
    )
    assert mention.selfmod_finding.severity is Severity.HIGH


def test_console_probe_base_severity_matches_the_console() -> None:
    from petasos.console.server import _maybe_fire_console_probe
    from petasos.pipeline import Pipeline

    pipeline = Pipeline(config=OldConfig())
    captured: list[Any] = []
    pipeline.record_selfmod = lambda _session_id, finding: captured.append(finding)  # type: ignore[method-assign, assignment]
    _maybe_fire_console_probe(pipeline)

    assert captured
    assert SELFMOD_BASE_SEVERITY["petasos.selfmod.console_probe"] == captured[0].severity.value
