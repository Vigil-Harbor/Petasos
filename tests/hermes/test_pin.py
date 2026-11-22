"""Managed pins use temporary files and a Hermes reader stand-in throughout."""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from petasos.config.layers import resolve
from petasos.config.schema import leaves, to_mapping
from petasos.config.sections import PetasosConfig
from petasos.hermes.commands import main
from petasos.hermes.dashboard.changes import clear_overrides, save_settings
from petasos.hermes.dashboard.errors import ApiError
from petasos.hermes.dashboard.values import hermes_merge
from petasos.hermes.doctor_pin import pin_report
from petasos.hermes.managed import read_managed
from petasos.hermes.pin_cmd import change_pin
from petasos.hermes.pinning import (
    LIMITS,
    OWNER,
    differences,
    leaf_paths,
    merge_pin,
    pin_values,
    remove_pin,
)
from petasos.hermes.settings import (
    PINNED_REFUSAL,
    HermesSettings,
    pinned_settings,
    profile_binding,
)

_PINNED = {"role": "coding", "level": "strict", "overrides": {}}


def _profile() -> dict[str, Any]:
    return {
        "plugins": {
            "enabled": ["petasos", "other"],
            "disabled": ["off"],
            "entries": {
                "petasos": {"settings": {"role": "coding", "level": "strict", "overrides": {}}}
            },
        }
    }


@pytest.fixture
def scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    directory = tmp_path / "managed"
    directory.mkdir()
    home = tmp_path / "profile"
    home.mkdir()
    profile = _profile()
    (home / "config.yaml").write_text(json.dumps(profile))
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(directory))

    def document() -> dict[str, Any]:
        path = directory / "config.yaml"
        return json.loads(path.read_text()) if path.exists() else {}

    module = SimpleNamespace(
        _DEFAULT_MANAGED_DIR=directory,
        get_managed_dir=lambda: directory,
        load_managed_config=document,
        managed_config_keys=lambda: {".".join(parts) for parts in leaf_paths(document())},
        _cached_read=lambda path, cache, parse: parse(path),
        fast_safe_load=yaml.safe_load,
        apply_managed_overlay=lambda raw: hermes_merge(raw, document()),
    )
    monkeypatch.setitem(sys.modules, "hermes_cli.managed_scope", module)
    monkeypatch.setattr("petasos.hermes.pin_cmd.effective_config", lambda: profile)
    monkeypatch.setattr("petasos.hermes.pin_cmd.hook_timeout", lambda: 30.0)
    monkeypatch.setattr(
        "petasos.hermes.doctor_pin.effective_config", lambda: hermes_merge(profile, document())
    )
    return SimpleNamespace(
        directory=directory, home=home, profile=profile, module=module, read=document
    )


def test_every_resolved_leaf_and_both_lists() -> None:
    profile = _profile()
    values = pin_values(profile, timeout=42.0)
    settings = values["plugins"]["entries"]["petasos"]["settings"]
    assert settings["overrides"] == to_mapping(
        resolve({"role": "coding", "level": "strict"}).config
    )
    for row in leaves(PetasosConfig):
        current = settings["overrides"]
        for part in row.path.split("."):
            current = current[part]
    assert values["plugins"]["enabled"] == ["petasos", "other"]
    assert values["plugins"]["disabled"] == ["off"]
    assert values["plugins"]["hook_callback_timeout"] == 42.0


@pytest.mark.parametrize("enabled,disabled", [([], []), (["petasos"], ["petasos"])])
def test_refuse_when_hermes_does_not_load_petasos(enabled: list[str], disabled: list[str]) -> None:
    with pytest.raises(ValueError, match="must be on"):
        pin_values({"plugins": {"enabled": enabled, "disabled": disabled}}, timeout=30)


def test_merge_and_remove_keep_unrelated_keys_and_dotted_rule_names() -> None:
    original = {
        "model": {"default": "example"},
        "plugins": {"entries": {"other": {"settings": {"a": 1}}}},
    }
    document = merge_pin(original, pin_values(_profile(), timeout=30))
    assert document["model"] == original["model"]
    assert remove_pin(document) == original
    assert [
        "plugins",
        "entries",
        "petasos",
        "settings",
        "overrides",
        "rules",
        "severity_overrides",
        "petasos.promptguard.injection",
    ] in document[OWNER]["paths"]
    assert remove_pin(merge_pin(document, pin_values(_profile(), timeout=30))) == original


def test_preview_has_no_write_and_discloses_scope(scope: SimpleNamespace) -> None:
    text, code = change_pin(scope.home)
    assert code == 0
    assert not (scope.directory / "config.yaml").exists()
    for phrase in (
        "Plugins kept on: petasos, other.",
        "Plugins kept off: off.",
        "No plugin can be turned on or off",
        "Job: coding. Strictness: strict.",
        "every profile",
        "nothing a profile holds",
        LIMITS,
    ):
        assert phrase in text


def test_direct_write_is_atomic_and_discloses_before_writing(
    scope: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    replace = os.replace
    seen = []

    def replace_after_disclosure(source: Path, target: Path) -> None:
        assert "Plugins kept on:" in capsys.readouterr().out
        assert target == scope.directory / "config.yaml"
        seen.append(target)
        replace(source, target)

    monkeypatch.setattr("petasos.hermes.pin_cmd.os.replace", replace_after_disclosure)
    text, code = change_pin(scope.home, write=True)
    assert code == 0 and seen
    assert "does not protect" in text
    assert scope.read()["plugins"]["enabled"] == ["petasos", "other"]
    assert not list(scope.directory.glob(".petasos-pin-*"))


def test_administrator_route_only_prepares_system_commands(
    scope: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("petasos.hermes.pin_cmd.writable", lambda path: False)
    text, code = change_pin(scope.home, write=True)
    assert code == 0
    assert not (scope.directory / "config.yaml").exists()
    commands = [
        shlex.split(line) for line in text.splitlines() if line.startswith(("mkdir ", "install "))
    ]
    assert [line[0] for line in commands] == ["mkdir", "install"]
    source = Path(commands[1][-2])
    assert json.loads(source.read_text())["plugins"]["enabled"] == ["petasos", "other"]
    if os.name != "nt":
        assert source.stat().st_mode & 0o777 == 0o600
        assert source.parent.stat().st_mode & 0o777 == 0o700
    assert commands[1][-1] == str(scope.directory / "config.yaml")


def test_unpin_refuses_profile_changes_until_explicitly_accepted(scope: SimpleNamespace) -> None:
    change_pin(scope.home, write=True)
    scope.profile["plugins"]["enabled"] = ["other"]
    (scope.home / "config.yaml").write_text(json.dumps(scope.profile))
    before = (scope.directory / "config.yaml").read_bytes()
    text, code = change_pin(scope.home, remove=True, write=True)
    assert code == 2 and "Plugins kept on" in text and "--accept-profile-changes" in text
    assert (scope.directory / "config.yaml").read_bytes() == before
    text, code = change_pin(scope.home, remove=True, write=True, accept_profile_changes=True)
    assert code == 0 and scope.read() == {}


def test_unpin_identical_profile_and_administrator_route(
    scope: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    change_pin(scope.home, write=True)
    assert differences(scope.profile, scope.read()) == ()
    monkeypatch.setattr("petasos.hermes.pin_cmd.writable", lambda path: False)
    text, code = change_pin(scope.home, remove=True, write=True)
    commands = [shlex.split(line) for line in text.splitlines() if line.startswith("install ")]
    assert code == 0 and json.loads(Path(commands[0][-2]).read_text()) == {}
    assert scope.read()


def test_pinned_and_partly_pinned_and_writable_states(
    scope: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    change_pin(scope.home, write=True)
    checks, facts, _ = pin_report(scope.profile)
    assert facts["state"] == "writable"
    assert "does not protect settings" in checks[0].summary
    monkeypatch.setattr("petasos.hermes.doctor_pin.writable", lambda path: False)
    monkeypatch.setattr("petasos.hermes.doctor_pin._file_writable", lambda scope: False)
    checks, facts, _ = pin_report(scope.profile)
    assert facts["state"] == "pinned" and "Only an administrator" in checks[0].summary
    assert facts["open_groups"] == [] and facts["unset_values"] == []
    document = scope.read()
    del document["plugins"]["disabled"]
    (scope.directory / "config.yaml").write_text(json.dumps(document))
    checks, facts, _ = pin_report(scope.profile)
    assert facts["state"] == "partly_pinned" and "Plugins kept off" in checks[0].meaning


def test_a_managed_file_written_by_hand_is_left_to_hermes_and_is_partly_pinned(
    scope: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the pin's record Petasos does not read the file whole, and says what is open."""
    change_pin(scope.home, write=True)
    document = scope.read()
    del document[OWNER]
    (scope.directory / "config.yaml").write_text(json.dumps(document))
    monkeypatch.setattr("petasos.hermes.doctor_pin.writable", lambda path: False)
    monkeypatch.setattr("petasos.hermes.doctor_pin._file_writable", lambda scope: False)

    assert pinned_settings() is None
    checks, facts, _ = pin_report(scope.profile)
    assert facts["state"] == "partly_pinned" and "Points per rule" in checks[0].meaning


def test_a_pin_is_read_whole_and_a_profile_cannot_add_to_it(scope: SimpleNamespace) -> None:
    """Hermes would merge a new entry into a pinned group. Petasos does not use it."""
    change_pin(scope.home, write=True)
    loosened = {
        "role": "general",
        "level": "relaxed",
        "overrides": {
            "rules": {"severity_overrides": {"command.destructive-recursive": "info"}},
            "frequency": {"weights": {"injection": 0.0}},
            "tools": {"aliases": {"terminal": "read_file"}},
            "scanners": {"semgrep": {"engine_path": "/tmp/not-the-engine"}},
        },
    }
    scope.profile["plugins"]["entries"]["petasos"]["settings"] = loosened
    (scope.home / "config.yaml").write_text(json.dumps(scope.profile))

    class Store:
        def get_config(self, key: str, default: object = None) -> object:
            merged = hermes_merge(scope.profile, scope.read())
            return merged["plugins"]["entries"]["petasos"]["settings"].get(key, default)

    merged_view = Store().get_config("overrides")
    assert isinstance(merged_view, dict)
    assert merged_view["rules"]["severity_overrides"]["command.destructive-recursive"] == "info"
    assert merged_view["tools"]["aliases"] == {"terminal": "read_file"}

    snapshot = HermesSettings(Store())()
    assert snapshot.config is not None
    assert snapshot.config == resolve(_PINNED).config
    assert "command.destructive-recursive" not in snapshot.config.rules.severity_overrides
    assert snapshot.config.tools.aliases == {}
    assert snapshot.config.scanners.semgrep.engine_path is None
    kind, settings = profile_binding(scope.home / "config.yaml")
    assert kind == "settings" and settings is not None
    assert settings["role"] == "coding" and settings["level"] == "strict"
    bound = HermesSettings(Store())
    bound.bind_profile(scope.home / "missing")
    assert bound().config == snapshot.config


def test_saves_are_refused_while_pinned(
    scope: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    """A save would be stored in the profile and then have no effect, so it is refused."""
    change_pin(scope.home, write=True)
    (scope.home / "plugins" / "petasos").mkdir(parents=True)
    (scope.home / "plugins" / "petasos" / "plugin.yaml").write_text("name: petasos\n")
    calls: list[object] = []

    def write(values: object, plugin_dir: Path) -> None:
        calls.append(values)

    with pytest.raises(ApiError) as caught:
        save_settings({}, {"level": "relaxed"}, plugin_dir=scope.home, write=write, secrets={})
    assert caught.value.code == "pinned" and caught.value.message == PINNED_REFUSAL
    with pytest.raises(ApiError):
        clear_overrides(
            {"overrides": {"fail_mode": "open"}},
            None,
            plugin_dir=scope.home,
            write=write,
            secrets={},
        )
    code = main(["config", "set", "level", "relaxed", "--home", str(scope.home)])
    assert code == 2 and PINNED_REFUSAL in capsys.readouterr().out
    assert calls == []


def test_pin_not_in_force_uses_machine_standin(
    scope: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    change_pin(scope.home, write=True)
    other = scope.home / "other-managed"
    other.mkdir()
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(other))
    scope.module.get_managed_dir = lambda: other
    scope.module.load_managed_config = lambda: {}
    scope.module.managed_config_keys = lambda: set()
    checks, facts, _ = pin_report(scope.profile)
    assert facts["state"] == "not_in_force" and checks[0].status == "fail"
    assert "Pin not in force" in checks[0].summary


@pytest.mark.parametrize("change", ["enabled", "list", "disabled"])
def test_disabled_pin_is_loud(scope: SimpleNamespace, change: str) -> None:
    change_pin(scope.home, write=True)
    document = scope.read()
    if change == "enabled":
        document["plugins"]["entries"]["petasos"]["settings"]["enabled"] = False
    elif change == "list":
        document["plugins"]["enabled"] = []
    else:
        document["plugins"]["disabled"] = ["petasos"]
    (scope.directory / "config.yaml").write_text(json.dumps(document))
    checks, _, _ = pin_report(scope.profile)
    assert any(check.id == "pin_disabled" and check.status == "fail" for check in checks)


def test_profile_differences_and_nullable_leaf_are_named(scope: SimpleNamespace) -> None:
    change_pin(scope.home, write=True)
    scope.profile["plugins"]["entries"]["petasos"]["settings"].update(
        {"level": "relaxed", "overrides": {"scanners": {"semgrep": {"engine_path": "/changed"}}}}
    )
    checks, facts, _ = pin_report(scope.profile)
    assert facts["profile_differences"]
    line = next(check for check in checks if check.id == "pin_profile")
    assert "Something tried" in line.summary and "Pinned values are in force" in line.meaning
    assert "Strictness" in line.meaning and "Engine location" in line.meaning


@pytest.mark.parametrize(
    "name", ["get_managed_dir", "load_managed_config", "managed_config_keys", "_cached_read"]
)
def test_missing_or_raising_reader_never_reports_pinned(scope: SimpleNamespace, name: str) -> None:
    change_pin(scope.home, write=True)
    setattr(scope.module, name, None)
    checks, facts, _ = pin_report(scope.profile)
    assert facts["state"] == "unknown"
    assert "cannot tell" in checks[0].summary


def test_raising_reader_fails_safe(scope: SimpleNamespace) -> None:
    def broken() -> None:
        raise RuntimeError("unavailable")

    scope.module.load_managed_config = broken
    with pytest.raises(ValueError, match="cannot tell"):
        read_managed()


def test_cli_flags(scope: SimpleNamespace, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["hermes", "pin", "--home", str(scope.home)]) == 0
    assert "Nothing was written" in capsys.readouterr().out
    assert main(["hermes", "pin", "--home", str(scope.home), "--write"]) == 0
    assert (
        main(["hermes", "unpin", "--home", str(scope.home), "--write", "--accept-profile-changes"])
        == 0
    )


def test_unpin_keeps_entries_added_to_a_formerly_empty_map() -> None:
    pinned = merge_pin({}, pin_values(_profile(), timeout=30))
    pinned["plugins"]["entries"]["petasos"]["settings"]["overrides"]["tools"]["aliases"]["new"] = (
        "terminal"
    )
    assert remove_pin(pinned) == {
        "plugins": {
            "entries": {
                "petasos": {"settings": {"overrides": {"tools": {"aliases": {"new": "terminal"}}}}}
            }
        }
    }


def test_unsupported_platform_writes_nothing(
    scope: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("petasos.hermes.managed.os", SimpleNamespace(name="nt", environ={}))
    text, code = change_pin(scope.home, write=True)
    assert code == 2 and text == "Machine-level pinning is not available on this platform.\n"
    assert not (scope.directory / "config.yaml").exists()


def test_failed_atomic_write_leaves_existing_document(
    scope: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = {"model": {"default": "keep"}}
    (scope.directory / "config.yaml").write_text(json.dumps(original))

    def broken(source: Path, target: Path) -> None:
        raise OSError("cannot replace")

    monkeypatch.setattr("petasos.hermes.pin_cmd.os.replace", broken)
    text, code = change_pin(scope.home, write=True)
    assert code == 2 and "cannot replace" in text
    assert scope.read() == original
    assert not list(scope.directory.glob(".petasos-pin-*"))


def test_bad_ownership_never_removes_unrelated_keys(scope: SimpleNamespace) -> None:
    document = merge_pin({}, pin_values(_profile(), timeout=30))
    document[OWNER]["paths"].append(["model", "default"])
    with pytest.raises(ValueError, match="unrelated"):
        remove_pin(document)


def test_status_exposes_pin_and_uses_effective_switches(scope: SimpleNamespace) -> None:
    from petasos.hermes.dashboard.scope import load_home
    from petasos.hermes.dashboard.status import status

    change_pin(scope.home, write=True)
    scope.profile["plugins"]["enabled"] = []
    (scope.home / "config.yaml").write_text(json.dumps(scope.profile))
    body = status(load_home(scope.home), home_label="sandbox")
    assert body["pin"]["state"] == "writable"
    assert "Pinned where this account can write" in body["who_can_change"]["agent"]
    assert LIMITS in body["who_can_change"]["administrator"]
    assert body["switches"]["hermes"]["on"] is True


@pytest.mark.parametrize("reference", ["${S1B_LANGUAGE}", "${env:S1B_LANGUAGE}"])
def test_unresolved_environment_reference_is_not_pinned(reference: str) -> None:
    profile = _profile()
    profile["plugins"]["entries"]["petasos"]["settings"]["overrides"] = {
        "scanners": {"presidio": {"language": reference}}
    }
    with pytest.raises(ValueError, match="environment reference"):
        pin_values(profile, timeout=30)


def test_doctor_names_environment_dependent_pin_values(scope: SimpleNamespace) -> None:
    change_pin(scope.home, write=True)
    document = scope.read()
    document["plugins"]["entries"]["petasos"]["settings"]["overrides"]["scanners"]["presidio"][
        "language"
    ] = "${S1B_LANGUAGE}"
    (scope.directory / "config.yaml").write_text(json.dumps(document))
    checks, facts, _ = pin_report(scope.profile)
    assert facts["environment_references"] is True
    assert "depend on environment variables" in checks[0].meaning


def test_bypassed_machine_pin_still_reports_the_active_overlay(
    scope: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    change_pin(scope.home, write=True)
    other = scope.home / "other-managed"
    other.mkdir()
    alternate = {
        "plugins": {"enabled": [], "entries": {"petasos": {"settings": {"enabled": False}}}}
    }
    (other / "config.yaml").write_text(json.dumps(alternate))
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(other))
    scope.module.get_managed_dir = lambda: other
    scope.module.load_managed_config = lambda: alternate
    scope.module.managed_config_keys = lambda: {".".join(p) for p in leaf_paths(alternate)}
    monkeypatch.setattr(
        "petasos.hermes.doctor_pin.effective_config",
        lambda: hermes_merge(scope.profile, alternate),
    )
    checks, facts, effective = pin_report(scope.profile)
    assert facts["state"] == "not_in_force" and checks[0].status == "fail"
    assert isinstance(effective, dict) and effective["plugins"]["enabled"] == []
    assert effective["plugins"]["entries"]["petasos"]["settings"]["enabled"] is False


def test_repin_captures_the_whole_pin_and_discloses_written_settings(
    scope: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A profile-only alias must not enter the pin shared with every other profile."""
    change_pin(scope.home, write=True)
    original = scope.read()["plugins"]["entries"]["petasos"]["settings"]
    scope.profile["plugins"]["entries"]["petasos"]["settings"] = {
        "role": "general",
        "overrides": {"tools": {"aliases": {"terminal": "read_file"}}},
    }
    (scope.home / "config.yaml").write_text(json.dumps(scope.profile))
    monkeypatch.setattr(
        "petasos.hermes.pin_cmd.effective_config",
        lambda: hermes_merge(scope.profile, scope.read()),
    )
    capsys.readouterr()
    preview, code = change_pin(scope.home)
    assert code == 0
    _text, code = change_pin(scope.home, write=True)
    assert code == 0
    disclosure = capsys.readouterr().out
    actual = scope.read()["plugins"]["entries"]["petasos"]["settings"]
    assert actual == original
    # The disclosure carries a JSON value, so the complete saved settings can be inspected.
    decoder = json.JSONDecoder()
    shown, _ = decoder.raw_decode(disclosure[disclosure.index("{") :])
    assert shown == actual
    shown_preview, _ = decoder.raw_decode(preview[preview.index("{") :])
    assert shown_preview == actual
