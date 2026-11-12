"""Saving and clearing settings through a stand-in for Hermes's writer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from petasos.hermes.dashboard.changes import clear_overrides, save_settings
from petasos.hermes.dashboard.errors import ApiError
from petasos.hermes.dashboard.values import hermes_merge

if TYPE_CHECKING:
    from pathlib import Path

_SECRETS = {"session_secret": "unset", "hash_key": "unset"}


class _Store:
    """Hermes's deep merge, including the list-replaces-mapping step."""

    def __init__(self) -> None:
        self.settings: dict[str, Any] = {
            "enabled": True,
            "role": "general",
            "level": "balanced",
            "overrides": {"fail_mode": "open", "scanners": {"prompt_guard": {"threshold": 0.5}}},
        }
        self.calls: list[dict[str, Any]] = []

    def write(self, values: Any, plugin_dir: Path) -> None:
        self.calls.append({"values": dict(values), "plugin_dir": plugin_dir})
        for key, value in values.items():
            current = self.settings.get(key)
            if isinstance(current, dict) and isinstance(value, dict):
                self.settings[key] = hermes_merge(current, value)
            else:
                self.settings[key] = value


def test_a_patch_keeps_a_sibling_override(tmp_path: Path) -> None:
    """Writing one override does not drop another that was already stored."""
    store = _Store()
    body = save_settings(
        store.settings,
        {"overrides": {"rules": {"confidence_floor": 0.8}}},
        plugin_dir=tmp_path,
        write=store.write,
        secrets=_SECRETS,
    )
    assert body["saved"] is True
    assert store.settings["overrides"]["fail_mode"] == "open"
    assert store.settings["overrides"]["rules"]["confidence_floor"] == 0.8
    assert store.settings["overrides"]["scanners"]["prompt_guard"]["threshold"] == 0.5


def test_clearing_one_override_removes_it_despite_the_merge(tmp_path: Path) -> None:
    """A list write replaces the mapping, so the cleared key does not survive."""
    store = _Store()
    body = clear_overrides(
        store.settings,
        "fail_mode",
        plugin_dir=tmp_path,
        write=store.write,
        secrets=_SECRETS,
    )
    assert body["cleared"] is True
    assert "fail_mode" not in store.settings["overrides"]
    assert store.settings["overrides"]["scanners"]["prompt_guard"]["threshold"] == 0.5
    written = [call["values"].get("overrides") for call in store.calls]
    assert [] in written


def test_clearing_every_override_leaves_an_empty_mapping(tmp_path: Path) -> None:
    """Clearing all overrides stores an empty mapping, not the previous keys."""
    store = _Store()
    body = clear_overrides(
        store.settings,
        None,
        plugin_dir=tmp_path,
        write=store.write,
        secrets=_SECRETS,
    )
    assert body["cleared"] is True
    assert store.settings["overrides"] == {}


def test_an_invalid_value_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    """The schema's message is returned with the path, and the writer is not called."""
    store = _Store()
    before = dict(store.settings)
    with pytest.raises(ApiError) as caught:
        save_settings(
            store.settings,
            {"role": "nope"},
            plugin_dir=tmp_path,
            write=store.write,
            secrets=_SECRETS,
        )
    assert caught.value.code == "invalid_settings"
    assert caught.value.path == "role"
    assert store.calls == []
    assert store.settings["role"] == before["role"]


def test_a_managed_refusal_is_reported_as_such(tmp_path: Path) -> None:
    """Hermes's PermissionError becomes a sentence about the administrator."""

    def _refuse(_values: Any, _plugin_dir: Path) -> None:
        raise PermissionError("administrator-managed")

    with pytest.raises(ApiError) as caught:
        save_settings(
            {},
            {"level": "strict"},
            plugin_dir=tmp_path,
            write=_refuse,
            secrets=_SECRETS,
        )
    assert caught.value.status == 403
    assert caught.value.code == "managed"
    assert "administrator" in caught.value.message


def test_a_restart_field_is_named(tmp_path: Path) -> None:
    """Changing a scanner threshold is saved and reported as needing a restart."""
    store = _Store()
    store.settings["overrides"] = {}
    body = save_settings(
        store.settings,
        {"overrides": {"scanners": {"prompt_guard": {"threshold": 0.2}}}},
        plugin_dir=tmp_path,
        write=store.write,
        secrets=_SECRETS,
    )
    assert "scanners.prompt_guard.threshold" in body["restart"]
    assert "restart" in body["restart_message"].lower()
    assert "PromptGuard sensitivity" in body["restart_message"]
    assert "An agent started from now on uses the saved value" in body["restart_message"]
    assert "already running keeps the previous value until it restarts" in body["restart_message"]
    assert "next tool call" not in body["restart_message"]


def test_a_live_change_says_it_applies_from_the_next_tool_call(tmp_path: Path) -> None:
    """A change with no restart says when it takes effect."""
    store = _Store()
    body = save_settings(
        store.settings,
        {"role": "research"},
        plugin_dir=tmp_path,
        write=store.write,
        secrets=_SECRETS,
    )
    assert body["restart"] == []
    assert body["restart_message"] == "Saved. Petasos uses it from the agent's next tool call."


def test_a_mixed_save_separates_restart_settings_from_live_ones(tmp_path: Path) -> None:
    """One save can do both, and the sentence says which is which."""
    store = _Store()
    body = save_settings(
        store.settings,
        {
            "overrides": {
                "rules": {"confidence_floor": 0.8},
                "scanners": {"prompt_guard": {"threshold": 0.2}},
            }
        },
        plugin_dir=tmp_path,
        write=store.write,
        secrets=_SECRETS,
    )
    assert body["restart"] == ["scanners.prompt_guard.threshold"]
    assert "started from now on" in body["restart_message"]
    assert "already running" in body["restart_message"]
    assert "next tool call" in body["restart_message"]


def test_secrets_are_not_accepted(tmp_path: Path) -> None:
    """The panel does not write the session secret."""
    store = _Store()
    with pytest.raises(ApiError) as caught:
        save_settings(
            {},
            {"session_secret": "nope"},
            plugin_dir=tmp_path,
            write=store.write,
            secrets=_SECRETS,
        )
    assert caught.value.code == "secret"
    assert store.calls == []
