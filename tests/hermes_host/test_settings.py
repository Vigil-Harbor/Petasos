"""Question 3: plugin settings round-trip through the real Hermes writer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.hermes_host.client import invoke
from tests.hermes_host.marks import requires_hermes_sandbox

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = requires_hermes_sandbox


def test_set_config_round_trip_and_unset_default(hermes_sandbox: Path) -> None:
    written = invoke(
        hermes_sandbox,
        {"action": "settings", "op": "set", "key": "level", "value": "strict"},
    )
    assert written["value"] == "strict"
    assert "level: strict" in written["yaml"]
    again = invoke(hermes_sandbox, {"action": "settings", "op": "get", "key": "level"})
    assert again["value"] == "strict"
    missing = invoke(
        hermes_sandbox,
        {"action": "settings", "op": "get", "key": "does_not_exist", "default": "fallback"},
    )
    assert missing["value"] == "fallback"


def test_dict_field_and_form_choice(hermes_sandbox: Path) -> None:
    # ``save_plugin_setting`` deep-merges into the mapping already on disk, so a
    # later write of ``overrides`` keeps keys that were stored earlier.
    written = invoke(
        hermes_sandbox,
        {"action": "settings", "op": "set", "key": "overrides.probe", "value": 7},
    )
    assert written["value"] == 7
    dotted = invoke(
        hermes_sandbox,
        {"action": "settings", "op": "get", "key": "overrides.probe"},
    )
    assert dotted["value"] == 7
    rejected = invoke(
        hermes_sandbox,
        {"action": "settings", "op": "form_set", "key": "role", "values": {"role": "nope"}},
    )
    assert "choices" in rejected["form_error"]


def test_env_expansion_is_reread(hermes_sandbox: Path) -> None:
    invoke(
        hermes_sandbox,
        {
            "action": "settings",
            "op": "set",
            "key": "role",
            "value": "${STANDIN_TOKEN}",
            "env": {"STANDIN_TOKEN": "first"},
        },
    )
    first = invoke(
        hermes_sandbox,
        {"action": "settings", "op": "get", "key": "role", "env": {"STANDIN_TOKEN": "first"}},
    )
    second = invoke(
        hermes_sandbox,
        {"action": "settings", "op": "get", "key": "role", "env": {"STANDIN_TOKEN": "second"}},
    )
    assert first["value"] == "first"
    assert second["value"] == "second"
    assert "${STANDIN_TOKEN}" in second["yaml"]
