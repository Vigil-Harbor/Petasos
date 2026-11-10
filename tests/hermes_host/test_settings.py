"""Question 3: plugin settings round-trip through the real Hermes writer."""

from __future__ import annotations

from tests.hermes_host.client import Sandbox, call
from tests.hermes_host.marks import requires_hermes_sandbox

pytestmark = requires_hermes_sandbox


def test_set_config_round_trip_and_unset_default(standin: Sandbox) -> None:
    written = call(standin, {"action": "settings", "op": "set", "key": "level", "value": "strict"})
    assert written["value"] == "strict"
    assert "level: strict" in written["yaml"]
    again = call(standin, {"action": "settings", "op": "get", "key": "level"})
    assert again["value"] == "strict"
    missing = call(
        standin,
        {"action": "settings", "op": "get", "key": "does_not_exist", "default": "fallback"},
    )
    assert missing["value"] == "fallback"


def test_dict_field_and_form_choice(standin: Sandbox) -> None:
    # ``save_plugin_setting`` deep-merges into the mapping already on disk, so a
    # later write of ``overrides`` keeps keys that were stored earlier.
    written = call(
        standin, {"action": "settings", "op": "set", "key": "overrides.probe", "value": 7}
    )
    assert written["value"] == 7
    dotted = call(standin, {"action": "settings", "op": "get", "key": "overrides.probe"})
    assert dotted["value"] == 7
    rejected = call(
        standin,
        {"action": "settings", "op": "form_set", "key": "role", "values": {"role": "nope"}},
    )
    assert "choices" in rejected["form_error"]


def test_env_expansion_is_reread(standin: Sandbox) -> None:
    call(
        standin,
        {
            "action": "settings",
            "op": "set",
            "key": "role",
            "value": "${STANDIN_TOKEN}",
            "env": {"STANDIN_TOKEN": "first"},
        },
    )
    first = call(
        standin,
        {"action": "settings", "op": "get", "key": "role", "env": {"STANDIN_TOKEN": "first"}},
    )
    second = call(
        standin,
        {"action": "settings", "op": "get", "key": "role", "env": {"STANDIN_TOKEN": "second"}},
    )
    assert first["value"] == "first"
    assert second["value"] == "second"
    assert "${STANDIN_TOKEN}" in second["yaml"]
