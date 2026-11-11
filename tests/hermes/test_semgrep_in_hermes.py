"""Semgrep cannot be turned on inside Hermes, and the form says so."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from petasos.config.layers import resolve
from petasos.hermes import semgrep_host
from petasos.hermes.dashboard.catalog import preview_settings, read_settings
from petasos.hermes.dashboard.changes import clear_overrides, save_settings
from petasos.hermes.dashboard.errors import ApiError
from petasos.hermes.doctor_advice import scanner_report
from petasos.scanners.registry import BuildContext, compose

if TYPE_CHECKING:
    from pathlib import Path

_SECRETS = {"session_secret": "unset", "hash_key": "unset"}
_ON = {"overrides": {"scanners": {"semgrep": {"enabled": "on"}}}}
_AUTO = {"overrides": {"scanners": {"semgrep": {"enabled": "auto"}}}}


class _Store:
    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self.settings: dict[str, Any] = {
            "enabled": True,
            "role": "general",
            "level": "balanced",
            "overrides": {},
        }
        if settings:
            self.settings.update(settings)
        self.calls: list[dict[str, Any]] = []

    def write(self, values: Any, plugin_dir: Path) -> None:
        self.calls.append(dict(values))
        self.settings.update(values)


def _row(body: dict[str, Any]) -> dict[str, Any]:
    return next(row for row in body["settings"] if row["path"] == semgrep_host.SEMGREP_ENABLED)


def test_the_form_offers_only_never_and_says_semgrep_cannot_run() -> None:
    """While Hermes cannot run Semgrep, Never is the one choice and the help says why."""
    row = _row(read_settings({}, secrets=_SECRETS))

    assert row["value"] == "off"
    assert row["choices"] == ["off"]
    assert row["choice_labels"] == {"off": "Never"}
    assert row["help"] == semgrep_host.SEMGREP_CANNOT_RUN
    assert "lifecycle" not in row["help"].casefold()


def test_the_form_offers_required_when_hermes_can_run_semgrep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one fact, patched true, restores the library's three choices and help."""
    monkeypatch.setattr(semgrep_host, "semgrep_can_run", lambda: True)
    row = _row(read_settings({}, secrets=_SECRETS))

    assert row["choices"] == ["auto", "on", "off"]
    assert row["choice_labels"]["auto"] == "Use it when it is installed"
    assert row["choice_labels"]["on"] == "Required"
    assert row["choice_labels"]["off"] == "Never"
    assert "cannot run inside Hermes" not in row["help"]


def test_a_stored_required_stays_visible_and_is_marked() -> None:
    """A hand-written Required is shown as itself, marked as unable to run."""
    row = _row(read_settings(_ON, secrets=_SECRETS))

    assert row["value"] == "on"
    assert row["choices"] == ["on", "off"]
    assert row["choice_labels"] == {"on": "Required (cannot run yet)", "off": "Never"}


def test_a_stored_auto_stays_visible_and_is_marked() -> None:
    """auto asks for a check that cannot start, so it is marked the same way."""
    row = _row(read_settings(_AUTO, secrets=_SECRETS))

    assert row["value"] == "auto"
    assert row["choices"] == ["auto", "off"]
    assert row["choice_labels"]["auto"] == "Use it when it is installed (cannot run yet)"


def test_saving_required_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    """A save that sets Semgrep to Required does not call the writer."""
    store = _Store()
    with pytest.raises(ApiError) as caught:
        save_settings(
            store.settings, _ON, plugin_dir=tmp_path, write=store.write, secrets=_SECRETS
        )

    assert caught.value.code == "semgrep_cannot_run"
    assert caught.value.message == semgrep_host.SEMGREP_TURN_ON_REFUSED
    assert caught.value.path == semgrep_host.SEMGREP_ENABLED
    assert store.calls == []


def test_a_preview_of_required_is_refused() -> None:
    """The preview refuses the same value, so the form does not offer a save."""
    body = preview_settings({}, _ON)

    assert body["valid"] is False
    assert body["changes"] == []
    assert body["problems"] == [
        {"path": semgrep_host.SEMGREP_ENABLED, "message": semgrep_host.SEMGREP_TURN_ON_REFUSED}
    ]


def test_changing_something_else_while_required_is_stored_is_refused(tmp_path: Path) -> None:
    """A save that leaves Required in place names the command that turns it off."""
    store = _Store({"overrides": {"scanners": {"semgrep": {"enabled": "on"}}}})
    with pytest.raises(ApiError) as caught:
        save_settings(
            store.settings,
            {"level": "strict"},
            plugin_dir=tmp_path,
            write=store.write,
            secrets=_SECRETS,
        )

    assert store.calls == []
    assert semgrep_host.SEMGREP_OFF_COMMAND in caught.value.message
    assert "not saved" in caught.value.message
    preview = preview_settings(store.settings, {"level": "strict"})
    assert preview["valid"] is False
    assert preview["problems"][0]["message"] == caught.value.message


def test_turning_required_off_is_saved(tmp_path: Path) -> None:
    """Changing Required to Never is the fix, and the writer is called."""
    store = _Store({"overrides": {"scanners": {"semgrep": {"enabled": "on"}}}})
    body = save_settings(
        store.settings,
        {"overrides": {"scanners": {"semgrep": {"enabled": "off"}}}},
        plugin_dir=tmp_path,
        write=store.write,
        secrets=_SECRETS,
    )

    assert body["saved"] is True
    assert store.calls
    assert store.settings["overrides"]["scanners"]["semgrep"]["enabled"] == "off"


def test_saving_auto_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    """auto would block tool calls that change things, so it is refused like Required."""
    store = _Store()
    with pytest.raises(ApiError) as caught:
        save_settings(
            store.settings, _AUTO, plugin_dir=tmp_path, write=store.write, secrets=_SECRETS
        )

    assert caught.value.message == semgrep_host.SEMGREP_TURN_ON_REFUSED
    assert store.calls == []
    assert preview_settings({}, _AUTO)["valid"] is False


def test_changing_something_else_while_auto_is_stored_is_refused(tmp_path: Path) -> None:
    store = _Store(_AUTO)
    with pytest.raises(ApiError) as caught:
        save_settings(
            store.settings,
            {"level": "strict"},
            plugin_dir=tmp_path,
            write=store.write,
            secrets=_SECRETS,
        )

    assert store.calls == []
    assert caught.value.message == semgrep_host.SEMGREP_LEFT_ON_REFUSED


def test_clearing_another_override_while_required_is_stored_is_refused(tmp_path: Path) -> None:
    """Resetting a different setting still leaves Required, so nothing is written."""
    store = _Store(
        {"overrides": {"fail_mode": "open", "scanners": {"semgrep": {"enabled": "on"}}}}
    )
    with pytest.raises(ApiError) as caught:
        clear_overrides(
            store.settings,
            "fail_mode",
            plugin_dir=tmp_path,
            write=store.write,
            secrets=_SECRETS,
        )

    assert store.calls == []
    assert semgrep_host.SEMGREP_OFF_COMMAND in caught.value.message


def test_clearing_required_itself_is_saved(tmp_path: Path) -> None:
    """Resetting Use Semgrep drops Required and the writer is called."""
    store = _Store({"overrides": {"scanners": {"semgrep": {"enabled": "on"}}}})
    body = clear_overrides(
        store.settings,
        semgrep_host.SEMGREP_ENABLED,
        plugin_dir=tmp_path,
        write=store.write,
        secrets=_SECRETS,
    )

    assert body["cleared"] is True
    assert store.calls


def test_required_can_be_saved_when_hermes_can_run_semgrep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Patching the one fact true lets a save set Required."""
    monkeypatch.setattr(semgrep_host, "semgrep_can_run", lambda: True)
    store = _Store()
    body = save_settings(
        store.settings, _ON, plugin_dir=tmp_path, write=store.write, secrets=_SECRETS
    )

    assert body["saved"] is True
    assert store.settings["overrides"]["scanners"]["semgrep"]["enabled"] == "on"


def _doctor(settings: dict[str, Any]) -> tuple[Any, dict[str, object]]:
    checks, _suggestions, rows = scanner_report(resolve(settings))
    check = next(item for item in checks if item.id == "scanner_semgrep")
    return check, next(item for item in rows if item["id"] == "semgrep")


def test_doctor_says_required_semgrep_is_blocking() -> None:
    """Where risky calls block, Required Semgrep is named as blocking, with the fix."""
    check, row = _doctor({"role": "research", **_ON})
    text = f"{check.summary} {check.meaning} {check.next_step} {row['reason']} {row['fix']}"

    assert check.summary == semgrep_host.SEMGREP_CANNOT_RUN
    assert check.meaning == (
        "It is set to Required, so tool calls that change things are blocked. "
        "Read-only tool calls still run."
    )
    assert check.next_step == semgrep_host.SEMGREP_OFF_COMMAND
    assert row["consequence"] is not None
    assert "lifecycle" not in text.casefold()
    assert "host_lifecycle" not in text


def test_doctor_says_what_semgrep_does_where_risky_calls_ask() -> None:
    """The general job asks, so the same setting makes those calls wait for a person."""
    check, _row_ = _doctor(_ON)

    assert check.meaning == (
        "It is set to Required, so tool calls that change things wait for a person. "
        "Read-only tool calls still run."
    )
    assert "added" not in check.meaning


def test_doctor_says_auto_does_the_same() -> None:
    """auto does not skip the check inside Hermes, and the report says what it does."""
    check, _row_ = _doctor({"role": "research", **_AUTO})

    assert check.summary == semgrep_host.SEMGREP_CANNOT_RUN
    assert check.meaning == (
        "It is set to run when it is installed, so tool calls that change things are "
        "blocked. Read-only tool calls still run."
    )
    assert check.next_step == semgrep_host.SEMGREP_OFF_COMMAND


def test_doctor_says_when_a_broken_check_is_let_through() -> None:
    check, _row_ = _doctor({"overrides": {"fail_mode": "open", **_ON["overrides"]}})

    assert check.meaning.startswith("It is set to Required. Tool calls still run without it")


def test_a_hand_written_required_is_kept_and_fails_closed() -> None:
    """Loading does not rewrite Required to off or auto, and the check cannot run."""
    resolved = resolve(_ON)
    assert resolved.config.scanners.semgrep.enabled == "on"
    composition = compose(resolved.config, BuildContext())
    status = next(item for item in composition.statuses if item.id == "semgrep")
    assert status.state == "unavailable"
    assert any(scanner.name == "semgrep" for scanner in composition.scanners)
