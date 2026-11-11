"""The two guardrail settings, who owns them, and what migration does with them."""

from __future__ import annotations

import pytest

from petasos.config.layers import ROLE_FIELDS, resolve
from petasos.config.migrate import migrate
from petasos.config.schema import ConfigError, leaves
from petasos.config.sections import PetasosConfig


def test_self_change_is_a_role_field_and_minutes_are_not() -> None:
    paths = {row.path for row in leaves(PetasosConfig)}

    assert "tools.self_change" in paths
    assert "tools.self_change_minutes" in paths
    assert "tools.self_change" in ROLE_FIELDS
    assert "tools.self_change_minutes" not in ROLE_FIELDS


def test_defaults_ask_for_thirty_minutes() -> None:
    tools = PetasosConfig().tools
    row = {item.path: item for item in leaves(PetasosConfig)}

    assert tools.self_change == "approve"
    assert tools.self_change_minutes == 30
    assert row["tools.self_change"].label == "When the agent tries to change its own guardrails"
    assert row["tools.self_change"].choice_labels is not None
    assert row["tools.self_change"].choice_labels["never"] == "Refuse the change"
    assert "cannot happen" not in row["tools.self_change"].choice_labels["never"].casefold()
    assert "shell" in row["tools.self_change"].help


def test_support_refuses_guardrail_changes_and_other_roles_ask() -> None:
    support = resolve({"role": "support"})

    assert support.config.tools.self_change == "never"
    assert support.origin["tools.self_change"] == "role"
    assert support.origin["tools.self_change_minutes"] == "default"
    for name in ("general", "coding", "research", "admin"):
        resolved = resolve({"role": name})
        assert resolved.config.tools.self_change == "approve"
        assert resolved.origin["tools.self_change"] == "default"


def test_minutes_are_whole_and_bounded() -> None:
    one = resolve({"overrides": {"tools": {"self_change_minutes": 1}}})
    longest = resolve({"overrides": {"tools": {"self_change_minutes": 1440}}})

    assert one.config.tools.self_change_minutes == 1
    assert longest.config.tools.self_change_minutes == 1440
    with pytest.raises(ConfigError):
        resolve({"overrides": {"tools": {"self_change_minutes": 0}}})
    with pytest.raises(ConfigError):
        resolve({"overrides": {"tools": {"self_change_minutes": 1441}}})
    with pytest.raises(ConfigError):
        resolve({"overrides": {"tools": {"self_change_minutes": 30.5}}})


def test_migration_does_not_write_the_new_fields() -> None:
    """An old section has no guardrail field, so migration adds no override for one."""
    migrated = migrate({"profile_name": "customer_service", "enabled": True})

    assert migrated.settings["role"] == "support"
    assert migrated.settings["overrides"] == {}
    assert resolve(migrated.settings).config.tools.self_change == "never"
    pinned = migrate({})
    assert pinned.settings["overrides"] == {"tools": {"dangerous_posture": "block"}}
    assert resolve(pinned.settings).config.tools.self_change == "approve"
