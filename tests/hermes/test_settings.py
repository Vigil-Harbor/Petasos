"""The settings source reads Hermes on each call and does not decide policy."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

import pytest

from petasos.config.layers import resolve
from petasos.hermes.settings import HermesSettings, profile_binding, write_settings

if TYPE_CHECKING:
    from pathlib import Path


class _Store:
    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self.values = {} if values is None else values
        self.calls = 0

    def get_config(self, key: str, default: object = None) -> object:
        """Provide get config for the test fixture."""
        self.calls += 1
        if key in self.values:
            return self.values[key]
        return default


def _drop_hermes(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(sys.modules):
        if name == "hermes_cli" or name.startswith("hermes_cli.") or name == "yaml":
            monkeypatch.delitem(sys.modules, name, raising=False)


def test_missing_hermes_uses_library_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Hermes install still yields the armed general/balanced snapshot."""
    _drop_hermes(monkeypatch)
    store = _Store()
    first = HermesSettings(store)()
    second = HermesSettings(store)()
    assert first.error is None
    assert first.armed is True
    assert first.config == resolve({}).config
    assert first.secrets.session_secret is None
    assert first.secrets.hash_key is None
    assert first.token == second.token
    assert store.calls >= 4


def test_source_does_not_mutate_the_host_mapping() -> None:
    """A nested overrides dict Hermes returned is copied before it is stored."""
    overrides: dict[str, Any] = {"fail_mode": "closed"}
    store = _Store({"overrides": overrides})
    source = HermesSettings(store)
    snap = source()
    assert snap.config is not None
    overrides["fail_mode"] = "open"
    assert snap.config.fail_mode == "closed"
    assert set(overrides) == {"fail_mode"}
    refreshed = source()
    assert refreshed.config is not None
    assert refreshed.config.fail_mode == "open"


def test_invalid_role_keeps_an_error_snapshot() -> None:
    """A bad role is reported. The snapshot carries no config for the enforcer to apply."""
    store = _Store({"role": "nope", "enabled": True})
    snap = HermesSettings(store)()
    assert snap.config is None
    assert snap.error is not None
    assert "role" in snap.error
    assert snap.armed is True


def test_invalid_enabled_does_not_disarm() -> None:
    """A value that is not true or false is an error, not an off switch."""
    store = _Store({"enabled": "yes"})
    snap = HermesSettings(store)()
    assert snap.error is not None
    assert snap.armed is True


def test_token_changes_when_a_setting_changes() -> None:
    """The token is the change signal. A new level is a new token."""
    store = _Store({"level": "balanced"})
    source = HermesSettings(store)
    before = source().token
    store.values["level"] = "strict"
    after = source().token
    assert before != after


def test_profile_file_distinguishes_legacy_from_plugin_settings(tmp_path: Path) -> None:
    """A top-level petasos section is detected and not returned as settings."""
    config = tmp_path / "config.yaml"
    config.write_text("petasos:\n  enabled: false\n  profile_name: research\n", encoding="utf-8")
    kind, settings = profile_binding(config)
    assert kind == "legacy"
    assert settings is None
    config.write_text(
        "plugins:\n  entries:\n    petasos:\n      settings:\n        role: research\n",
        encoding="utf-8",
    )
    kind, settings = profile_binding(config)
    assert kind == "settings"
    assert settings is not None
    assert settings["role"] == "research"
    settings["role"] = "admin"
    again, fresh = profile_binding(config)
    assert again == "settings"
    assert fresh is not None
    assert fresh["role"] == "research"


def test_empty_profile_section_is_not_legacy(tmp_path: Path) -> None:
    """An empty petasos section is the old plugin's 'no section' case."""
    config = tmp_path / "config.yaml"
    config.write_text("petasos: {}\n", encoding="utf-8")
    assert profile_binding(config) == ("empty", None)


def test_bound_profile_is_read_on_the_next_call(tmp_path: Path) -> None:
    """After a profile bind, the file is the source and the context is not."""
    config = tmp_path / "config.yaml"
    config.write_text(
        "plugins:\n  entries:\n    petasos:\n      settings:\n        level: strict\n",
        encoding="utf-8",
    )
    store = _Store({"level": "relaxed"})
    source = HermesSettings(store)
    relaxed = source().config
    assert relaxed is not None
    assert relaxed.fail_mode == "degraded"
    source.bind_profile(tmp_path)
    bound = source().config
    assert bound is not None
    assert bound.fail_mode == "closed"


def test_writer_reports_a_missing_hermes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The writer does not invent a config file when Hermes is not installed."""
    _drop_hermes(monkeypatch)
    with pytest.raises(RuntimeError, match="not available"):
        write_settings({"enabled": False}, plugin_dir=tmp_path)
