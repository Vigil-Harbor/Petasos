"""The configuration tree: defaults, floors, description, and the layer boundary."""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from petasos.config.schema import ConfigError, describe, from_mapping, to_mapping
from petasos.config.sections import PetasosConfig

_TYPES = {
    "bool",
    "int",
    "float",
    "str",
    "choice",
    "tuple[str, ...]",
    "mapping[str, float]",
    "mapping[str, str]",
}
_RESTART_ROOTS = (
    "scanners.prompt_guard.",
    "scanners.presidio.",
    "scanners.semgrep.",
)
_CONFIG_ROOT = Path("petasos/config")


def _errors(document: dict[str, object]) -> tuple[tuple[str, str], ...]:
    with pytest.raises(ConfigError) as caught:
        from_mapping(PetasosConfig, document)
    return caught.value.errors


def _has(errors: tuple[tuple[str, str], ...], path: str) -> bool:
    return any(item == path or item.startswith(path) for item, _message in errors)


def test_mapping_round_trip_keeps_a_fresh_config() -> None:
    fresh = PetasosConfig()

    assert from_mapping(PetasosConfig, to_mapping(fresh)) == fresh


def test_mapping_round_trip_keeps_a_changed_config() -> None:
    changed = from_mapping(
        PetasosConfig,
        {
            "fail_mode": "closed",
            "rules": {"confidence_floor": 0.4, "injection_floor_scope": "inbound"},
            "scanners": {"presidio": {"entities_extra": ["url"]}},
            "frequency": {"weights": {"petasos.syntactic.injection.*": 4}},
        },
    )

    assert from_mapping(PetasosConfig, to_mapping(changed)) == changed
    assert changed.scanners.presidio.entities_extra == ("URL",)
    assert changed.frequency.weights is not None
    assert dict(changed.frequency.weights) == {"petasos.syntactic.injection.*": 4.0}


def test_replace_revalidates() -> None:
    replaced = replace(PetasosConfig(), fail_mode="open")

    assert replaced.fail_mode == "open"
    with pytest.raises(ConfigError):
        replace(PetasosConfig().escalation, tier3=10.0)


def test_describe_covers_every_leaf() -> None:
    rows = describe(PetasosConfig)

    assert rows
    assert len({row.path for row in rows}) == len(rows)
    for row in rows:
        assert row.help.strip()
        assert row.type_name in _TYPES
        assert row.audience in ("advanced", "expert")
        restart = row.path.startswith(_RESTART_ROOTS)
        assert row.restart is restart


def test_expert_fields_are_the_internals() -> None:
    expert = {row.path for row in describe(PetasosConfig) if row.audience == "expert"}

    assert expert == {
        "scanners.breaker_threshold",
        "scanners.breaker_cooldown_seconds",
        "tools.lineage.max_depth",
        "tools.lineage.max_edges",
        "tools.lineage.edge_ttl_seconds",
        "alerting.cooldown_seconds",
        "alerting.per_minute_cap",
        "alerting.per_hour_cap",
        "alerting.critical_per_minute_cap",
        "alerting.high_severity_threshold",
        "alerting.rapid_fire_count",
        "alerting.rapid_fire_window_seconds",
        "alerting.cross_session_burst_count",
        "alerting.cross_session_burst_window_seconds",
        "alerting.pii_volume_threshold",
        "alerting.pii_volume_window_seconds",
        "alerting.ring_buffer_capacity",
        "alerting.per_session_contribution_cap",
        "alerting.max_session_contribution_entries",
        "sessions.max",
        "sessions.ttl_seconds",
        "sessions.max_new_per_minute",
        "sessions.max_tombstones",
    }


def test_scanner_defaults_match_the_stated_constants() -> None:
    fresh = PetasosConfig()

    assert fresh.scanners.prompt_guard.enabled == "auto"
    assert fresh.scanners.prompt_guard.threshold == 0.9
    assert fresh.scanners.presidio.enabled == "auto"
    assert fresh.scanners.presidio.language == "en"
    assert fresh.scanners.presidio.score_threshold == 0.35
    assert fresh.scanners.presidio.entities is None
    assert fresh.scanners.semgrep.enabled == "off"


def test_non_positive_tier1_is_accepted_when_the_tiers_still_ascend() -> None:
    config = from_mapping(PetasosConfig, {"escalation": {"tier1": 0, "tier2": 1, "tier3": 30}})

    assert config.escalation.tier1 == 0.0
    assert config.escalation.tier3 == 30.0


@pytest.mark.parametrize(
    ("document", "path"),
    [
        ({"escalation": {"tier3": 29.9}}, "escalation.tier3"),
        ({"escalation": {"tier1": 40, "tier2": 30, "tier3": 50}}, "escalation"),
        ({"rules": {"confidence_floor": 1.1}}, "rules.confidence_floor"),
        ({"rules": {"confidence_floor": -0.1}}, "rules.confidence_floor"),
        (
            {"rules": {"suppress": ["petasos.syntactic.structural.oversized-payload"]}},
            "rules.suppress[0]",
        ),
        ({"rules": {"suppress": ["petasos.selfmod.config_write"]}}, "rules.suppress[0]"),
        (
            {"rules": {"suppress": ["petasos.syntactic.injection.ignore-previous"]}},
            "rules.suppress[0]",
        ),
        (
            {
                "rules": {
                    "severity_overrides": {
                        "petasos.syntactic.structural.binary-content": "critical"
                    }
                }
            },
            "rules.severity_overrides.petasos.syntactic.structural.binary-content",
        ),
        (
            {"rules": {"severity_overrides": {"petasos.selfmod.config_ref": "low"}}},
            "rules.severity_overrides.petasos.selfmod.config_ref",
        ),
        (
            {"rules": {"severity_overrides": {"petasos.selfmod.unknown": "critical"}}},
            "rules.severity_overrides.petasos.selfmod.unknown",
        ),
        ({"rules": {"severity_overrides": {"petasos.promptguard.injection": "loud"}}}, "rules"),
        (
            {"rules": {"suppress": ["petasos.syntactic.command.pipe-to-shell"] * 2}},
            "rules.suppress",
        ),
        ({"scanners": {"presidio": {"entities": []}}}, "scanners.presidio.entities"),
        ({"scanners": {"presidio": {"entities": ["not_a_type"]}}}, "scanners.presidio.entities"),
        (
            {"scanners": {"presidio": {"entities_extra": "URL"}}},
            "scanners.presidio.entities_extra",
        ),
        (
            {"scanners": {"presidio": {"score_threshold": 1.1}}},
            "scanners.presidio.score_threshold",
        ),
        ({"scanners": {"presidio": {"language": "  "}}}, "scanners.presidio.language"),
        (
            {"scanners": {"semgrep": {"engine_path": "relative/semgrep"}}},
            "scanners.semgrep.engine_path",
        ),
        ({"scanners": {"semgrep": {"engine_sha256": "abcd"}}}, "scanners.semgrep.engine_sha256"),
        ({"scanners": {"semgrep": {"request_timeout_seconds": 0.5}}}, "scanners.semgrep"),
        ({"scanners": {"semgrep": {"max_source_bytes": 100}}}, "scanners.semgrep"),
        ({"scanners": {"timeout_seconds": 0}}, "scanners.timeout_seconds"),
        ({"scanners": {"timeout_seconds": 61}}, "scanners.timeout_seconds"),
        ({"scanners": {"breaker_threshold": True}}, "scanners.breaker_threshold"),
        ({"startup": {"wait_seconds": 0}}, "startup.wait_seconds"),
        ({"frequency": {"weights": {"a.*.b": 1}}}, "frequency.weights"),
        ({"frequency": {"weights": {"": 1}}}, "frequency.weights"),
        ({"frequency": {"half_life_seconds": 0}}, "frequency.half_life_seconds"),
        ({"alerting": {"rapid_fire_count": 1001}}, "alerting.rapid_fire_count"),
        ({"alerting": {"cross_session_burst_count": 1001}}, "alerting.cross_session_burst_count"),
        (
            {"alerting": {"per_session_contribution_cap": 6}},
            "alerting.per_session_contribution_cap",
        ),
        ({"tools": {"aliases": {"shell": "  "}}}, "tools.aliases.shell"),
        ({"tools": {"exempt": ["exec"], "aliases": {"shell": "Exec"}}}, "tools.aliases"),
        ({"tools": {"delegate_names": "delegate_task"}}, "tools.delegate_names"),
        ({"egress": {"sink_tools": "send_email"}}, "egress.sink_tools"),
        ({"egress": {"taint_namespaces": ""}}, "egress.taint_namespaces"),
        ({"sessions": {"max": True}}, "sessions.max"),
        ({"fail_mode": "maybe"}, "fail_mode"),
        ({"anonymization": {"enabled": 1}}, "anonymization.enabled"),
    ],
)
def test_invalid_document_names_the_path(document: dict[str, object], path: str) -> None:
    assert _has(_errors(document), path)


def test_injection_rules_can_be_suppressed_when_the_floor_is_inbound() -> None:
    config = from_mapping(
        PetasosConfig,
        {
            "rules": {
                "injection_floor_scope": "inbound",
                "suppress": ["petasos.syntactic.injection.ignore-previous"],
            }
        },
    )

    assert config.rules.suppress == ("petasos.syntactic.injection.ignore-previous",)


def test_selfmod_severity_may_rise_and_may_stay() -> None:
    raised = from_mapping(
        PetasosConfig,
        {"rules": {"severity_overrides": {"petasos.selfmod.config_ref": "critical"}}},
    )
    same = from_mapping(
        PetasosConfig,
        {"rules": {"severity_overrides": {"petasos.selfmod.config_write": "critical"}}},
    )

    assert raised.rules.severity_overrides["petasos.selfmod.config_ref"] == "critical"
    assert same.rules.severity_overrides["petasos.selfmod.config_write"] == "critical"


def test_alias_values_are_stripped() -> None:
    config = from_mapping(PetasosConfig, {"tools": {"aliases": {"shell": " exec "}}})

    assert config.tools.aliases["shell"] == "exec"


def test_hash_mode_without_a_key_is_not_a_config_error() -> None:
    config = from_mapping(PetasosConfig, {"anonymization": {"enabled": True, "mode": "hash"}})

    assert config.anonymization.mode == "hash"
    assert not hasattr(config, "hash_key")


def test_config_modules_import_nothing_above_the_config_layer() -> None:
    offenders: list[str] = []
    for path in sorted(_CONFIG_ROOT.rglob("*.py")):
        if path.name == "__init__.py" and path.parent == _CONFIG_ROOT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules: list[str | None]
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module]
            else:
                continue
            for module in modules:
                if module is None or not module.startswith("petasos"):
                    continue
                if module == "petasos._types" or module.startswith("petasos._types."):
                    continue
                if module == "petasos.config" or module.startswith("petasos.config."):
                    continue
                offenders.append(f"{path}: {module}")

    assert offenders == []
