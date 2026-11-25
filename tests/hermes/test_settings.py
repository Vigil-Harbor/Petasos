"""The settings source reads Hermes on each call and does not decide policy."""

from __future__ import annotations

import sys
from contextlib import closing
from typing import TYPE_CHECKING, Any

import pytest

from petasos.config.layers import LEVELS, ROLES, resolve
from petasos.hermes.settings import HermesSettings, profile_binding, write_settings

if TYPE_CHECKING:
    from pathlib import Path


class _Store:
    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self.values = {} if values is None else values
        self.calls = 0

    def get_config(self, key: str, default: object = None) -> object:
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


@pytest.mark.parametrize("role", tuple(ROLES))
@pytest.mark.parametrize("level", tuple(LEVELS))
def test_built_in_thresholds_do_not_warn(
    role: str, level: str, caplog: pytest.LogCaptureFixture
) -> None:
    from petasos.enforce import Enforcer, ToolCall

    with closing(
        Enforcer(HermesSettings(_Store({"role": role, "level": level})), registry=())
    ) as enforcer:
        enforcer.start()
        assert enforcer.settle()
        caplog.clear()
        with caplog.at_level("WARNING", logger="petasos.session.guard"):
            enforcer.tool_result(ToolCall(tool="read_file", args={}, session="s"), "hello")
        assert not [record for record in caplog.records if record.name == "petasos.session.guard"]


def test_explicit_thresholds_warn_even_when_they_match_a_level(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from petasos.enforce import Enforcer, ToolCall

    store = _Store({"level": "relaxed"})
    with closing(Enforcer(HermesSettings(store), registry=())) as enforcer:
        enforcer.start()
        assert enforcer.settle()
        call = ToolCall(tool="read_file", args={}, session="s")
        enforcer.tool_result(call, "hello")
        store.values["overrides"] = {"escalation": {"tier1": 25.0}}
        enforcer.refresh()
        caplog.clear()
        with caplog.at_level("WARNING", logger="petasos.session.guard"):
            enforcer.tool_result(call, "hello")
        assert [record for record in caplog.records if record.name == "petasos.session.guard"]
        store.values["overrides"] = {}
        enforcer.refresh()
        caplog.clear()
        enforcer.tool_result(call, "hello")
        assert not [record for record in caplog.records if record.name == "petasos.session.guard"]


class _RewrittenStore:
    """A store whose whole document is replaced after ``switch_after`` reads."""

    def __init__(self, before: dict[str, Any], after: dict[str, Any], switch_after: int) -> None:
        self._before = before
        self._after = after
        self._switch_after = switch_after
        self.calls = 0

    def get_config(self, key: str, default: object = None) -> object:
        document = self._before if self.calls < self._switch_after else self._after
        self.calls += 1
        return document.get(key, default)


@pytest.mark.parametrize("switch_after", [1, 2, 3])
def test_a_write_between_reads_never_yields_a_mixed_document(switch_after: int) -> None:
    """A settings write that lands mid-read gives one stored document, not a blend."""
    before = {"role": "general", "overrides": {"tools": {"self_change": "never"}}}
    after = {"role": "support", "overrides": {}}
    stored = [resolve(before).config, resolve(after).config]
    assert all(config.tools.self_change == "never" for config in stored)

    snap = HermesSettings(_RewrittenStore(before, after, switch_after))()

    assert snap.error is None
    assert snap.config in stored


def test_settings_that_keep_changing_are_a_rejected_read() -> None:
    """A store rewritten on every read gives an error snapshot and no config to apply."""

    class _Churning:
        def __init__(self) -> None:
            self.calls = 0

        def get_config(self, key: str, default: object = None) -> object:
            self.calls += 1
            if key == "overrides":
                return {"tools": {"self_change_minutes": self.calls}}
            return default

    store = _Churning()
    snap = HermesSettings(store)()

    assert snap.config is None
    assert snap.error is not None
    assert snap.armed is True
    assert store.calls <= 16


_NEVER = {"tools": {"self_change": "never"}}
_DISARM = "hermes plugins disable petasos"


def _guarded(store: _Store) -> Any:
    from petasos.enforce import ApprovalGrant, Enforcer, HostInfo
    from petasos.hermes.guardrail import hermes_surface

    host = HostInfo(
        approve_directive=True,
        approval_grant=ApprovalGrant,
        subagent_hooks=False,
        guardrail_surface=lambda: hermes_surface(()),
    )
    enforcer = Enforcer(HermesSettings(store), host=host, registry=())
    enforcer.start()
    assert enforcer.settle()
    return enforcer


def _disarm(enforcer: Any) -> object:
    from petasos.enforce import ToolCall

    return enforcer.tool_call(ToolCall(tool="terminal", args={"command": _DISARM}, session="s"))


@pytest.mark.parametrize(
    "stored",
    [
        pytest.param({}, id="block-removed"),
        pytest.param({"overrides": None}, id="overrides-null"),
        pytest.param({"overides": _NEVER}, id="misspelt-key"),
        pytest.param({"enabled": "yes", "overrides": {}}, id="enabled-text"),
        pytest.param({"role": 7, "overrides": {}}, id="role-number"),
        pytest.param({"level": "nope", "enabled": False}, id="unknown-level"),
    ],
)
def test_a_lost_or_malformed_block_keeps_the_last_good_settings(
    stored: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """After one good load, a wiped or broken block is a rejected reload."""
    from petasos.enforce import Approve, Block

    store = _Store({"overrides": _NEVER})
    with closing(_guarded(store)) as enforcer:
        assert isinstance(_disarm(enforcer), Block)
        store.values = dict(stored)
        caplog.clear()
        with caplog.at_level("WARNING"):
            enforcer.refresh()
            decision = _disarm(enforcer)
        assert isinstance(decision, Block)
        assert enforcer.status().armed is True
        assert any("PETASOS_RELOAD_FAILED" in record.getMessage() for record in caplog.records)
        store.values = {"overrides": {"tools": {"self_change": "approve"}}}
        enforcer.refresh()
        assert isinstance(_disarm(enforcer), Approve)


def test_a_first_start_with_no_block_is_armed_with_the_defaults(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """With no block ever seen, the defaults are the settings and nothing is rejected."""
    store = _Store()
    source = HermesSettings(store)
    with caplog.at_level("WARNING"):
        first = source()
        again = source()
        with closing(_guarded(store)) as enforcer:
            enforcer.refresh()
            assert enforcer.status().armed is True
    assert first.error is None
    assert first.armed is True
    assert first.config == resolve({}).config
    assert again.error is None
    assert again.token == first.token
    assert not any("PETASOS_RELOAD_FAILED" in record.getMessage() for record in caplog.records)


def test_a_removed_block_is_an_error_only_after_a_good_load() -> None:
    """The source rejects a missing block once it has read a good one, not before."""
    store = _Store()
    source = HermesSettings(store)
    assert source().error is None
    store.values = {"role": "coding"}
    assert source().error is None
    store.values = {}
    missing = source()
    assert missing.config is None
    assert missing.error is not None
    assert "missing" in missing.error
    store.values = {"level": "strict"}
    assert source().error is None


@pytest.mark.parametrize(
    "stored",
    [{"role": "coding"}, {"overrides": _NEVER}, {"enabled": False}],
    ids=["only-role", "only-overrides", "only-enabled"],
)
def test_a_partial_block_still_loads_after_a_good_load(stored: dict[str, Any]) -> None:
    """An absent key is the layer below it, not an error, while any key is stored."""
    store = _Store({"role": "support", "level": "strict", "overrides": {}})
    source = HermesSettings(store)
    assert source().error is None
    store.values = dict(stored)
    snap = source()
    assert snap.error is None
    assert snap.config == resolve(stored).config


def test_null_overrides_is_malformed_even_at_first_start() -> None:
    """A stored null is not an empty group. It is reported, and the enforcer keeps its floor."""
    snap = HermesSettings(_Store({"overrides": None}))()
    assert snap.config is None
    assert snap.error is not None
    assert "overrides" in snap.error


_STRICT_FILE = "plugins:\n  entries:\n    petasos:\n      settings:\n        level: strict\n"
_EMPTY_FILE = "plugins:\n  entries:\n    petasos:\n      settings: {}\n"


def test_a_bound_profile_whose_block_empties_is_not_a_reset(tmp_path: Path) -> None:
    """The rule for a lost block holds for a named profile, not only for the context."""
    config = tmp_path / "config.yaml"
    config.write_text(_STRICT_FILE, encoding="utf-8")
    source = HermesSettings(_Store())
    source.bind_profile(tmp_path)
    assert source().error is None
    config.write_text(_EMPTY_FILE, encoding="utf-8")
    emptied = source()
    assert emptied.config is None
    assert emptied.error is not None


def test_unbinding_to_an_empty_context_is_not_a_reset(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(_STRICT_FILE, encoding="utf-8")
    source = HermesSettings(_Store())
    source.bind_profile(tmp_path)
    assert source().error is None
    source.bind_profile(None)
    unbound = source()
    assert unbound.config is None
    assert "missing" in (unbound.error or "")


def test_removing_a_pin_over_an_empty_context_is_not_a_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from petasos.hermes import settings as module

    monkeypatch.setattr(module, "pinned_settings", lambda: {"level": "strict"})
    source = HermesSettings(_Store())
    assert source().error is None
    monkeypatch.setattr(module, "pinned_settings", lambda: None)
    unpinned = source()
    assert unpinned.config is None
    assert "missing" in (unpinned.error or "")
