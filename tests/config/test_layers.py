"""Roles, levels, and resolution."""

from __future__ import annotations

import pytest

from petasos.config.layers import (
    LEVEL_FIELDS,
    LEVEL_NAMES,
    LEVELS,
    ROLE_FIELDS,
    ROLE_NAMES,
    ROLES,
    document_fields,
    resolve,
)
from petasos.config.schema import ConfigError, describe, to_mapping
from petasos.config.sections import PetasosConfig


def test_axes_are_disjoint_and_name_real_leaves() -> None:
    leaves = {row.path for row in describe(PetasosConfig)}

    assert ROLE_FIELDS.isdisjoint(LEVEL_FIELDS)
    assert leaves >= ROLE_FIELDS
    assert leaves >= LEVEL_FIELDS


def test_every_builtin_stays_inside_its_axis() -> None:
    for role in ROLES.values():
        assert document_fields(role.document) <= ROLE_FIELDS
        assert role.suggests in LEVEL_NAMES
    for level in LEVELS.values():
        assert document_fields(level.document) <= LEVEL_FIELDS


def test_general_plus_balanced_equals_the_defaults() -> None:
    resolved = resolve({"role": "general", "level": "balanced"})

    assert to_mapping(resolved.config) == to_mapping(PetasosConfig())
    assert resolved.settings.enabled is True
    assert resolved.settings.overrides == {}


def test_origin_names_the_layer_that_supplied_each_leaf() -> None:
    resolved = resolve(
        {
            "role": "coding",
            "level": "relaxed",
            "overrides": {"fail_mode": "open", "rules": {"confidence_floor": 0.2}},
        }
    )

    for path, source in resolved.origin.items():
        if path == "fail_mode" or path == "rules.confidence_floor":
            assert source == "override"
        elif path in document_fields(ROLES["coding"].document):
            assert source == "role"
        elif path in LEVEL_FIELDS:
            assert source == "level"
        else:
            assert source == "default"
    assert set(resolved.origin) == {row.path for row in describe(PetasosConfig)}


def test_balanced_origin_is_level_for_the_level_fields() -> None:
    resolved = resolve({})

    for row in describe(PetasosConfig):
        expected = "level" if row.path in LEVEL_FIELDS else "default"
        assert resolved.origin[row.path] == expected


def test_unknown_role_and_level_name_the_valid_choices() -> None:
    with pytest.raises(ConfigError) as caught:
        resolve({"role": "code_generation", "level": "iron"})

    text = str(caught.value)
    assert 'unknown role "code_generation"' in text
    assert 'Did you mean "coding"' in text
    assert "general, coding, research, support, admin" in text
    assert 'unknown level "iron"' in text
    assert 'Did you mean "balanced"' in text


def test_retired_levels_say_what_to_do_instead() -> None:
    with pytest.raises(ConfigError) as caught:
        resolve({"level": "tin"})

    assert "Tin is not a level" in str(caught.value)

    with pytest.raises(ConfigError) as caught:
        resolve({"level": "titanium"})

    assert "Titanium is not a level" in str(caught.value)


def test_bad_override_is_reported_under_overrides() -> None:
    with pytest.raises(ConfigError) as caught:
        resolve({"overrides": {"escalation": {"tier1": "high"}}})

    assert caught.value.errors[0][0] == "overrides.escalation.tier1"


def test_unknown_settings_key_suggests_a_neighbor() -> None:
    with pytest.raises(ConfigError) as caught:
        resolve({"roles": "coding"})

    assert caught.value.errors[0][0] == "roles"
    assert "role" in caught.value.errors[0][1]


@pytest.mark.parametrize("role", ROLE_NAMES)
@pytest.mark.parametrize("level", LEVEL_NAMES)
def test_floors_hold_against_every_layer(role: str, level: str) -> None:
    with pytest.raises(ConfigError) as tier:
        resolve({"role": role, "level": level, "overrides": {"escalation": {"tier3": 10}}})
    with pytest.raises(ConfigError) as structural:
        resolve(
            {
                "role": role,
                "level": level,
                "overrides": {
                    "rules": {"suppress": ["petasos.syntactic.structural.oversized-payload"]}
                },
            }
        )

    assert tier.value.errors[0][0].startswith("overrides.escalation")
    assert structural.value.errors[0][0].startswith("overrides.rules.suppress")


def test_coding_cannot_keep_injection_suppressions_when_the_floor_widens() -> None:
    with pytest.raises(ConfigError) as caught:
        resolve({"role": "coding", "overrides": {"rules": {"injection_floor_scope": "all"}}})

    assert "cannot be suppressed" in str(caught.value) or "inbound" in str(caught.value)


def test_enabled_is_not_part_of_the_config() -> None:
    resolved = resolve({"enabled": False})

    assert resolved.settings.enabled is False
    assert not hasattr(resolved.config, "enabled")
    assert "enabled" not in {row.path for row in describe(PetasosConfig)}
