"""PET-222: observe Hermes approval hooks as enforcement events.

Handlers are called directly. No live Hermes process. The spool is the
conftest-isolated temp file.
"""

from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

import petasos.console._events as ev
from petasos.console.server import _BLOCK_EVENT_TYPES, _MAX_REASON_LEN, _enforcement_summary

if TYPE_CHECKING:
    import types

_REF_PLUGIN_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "deployment"
    / "reference_plugin"
    / "__init__.py"
)

_CHOICES = (
    "once",
    "session",
    "always",
    "deny",
    "timeout",
    "cancelled",
    "notify_failed",
    "smart_approve",
    "smart_deny",
)


def _import_reference_plugin() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "petasos_reference_plugin_pet222", str(_REF_PLUGIN_PATH)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ref() -> types.ModuleType:
    return _import_reference_plugin()


def _payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "command": "<terminal> (plugin approval rule)",
        "description": "run a command",
        "pattern_key": "plugin_rule:destructive-recursive",
        "pattern_keys": ["plugin_rule:destructive-recursive"],
        "session_key": "sess-key",
        "surface": "cli",
        "session_id": "sess-id",
        "tool_call_id": "tc-1",
        "turn_id": "turn-1",
    }
    base.update(overrides)
    return base


def _read_spool() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        with open(ev._spool_path(), encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped:
                    out.append(json.loads(stripped))
    except FileNotFoundError:
        return []
    return out


def _spool_bytes() -> bytes:
    try:
        with open(ev._spool_path(), "rb") as handle:
            return handle.read()
    except FileNotFoundError:
        return b""


def _only_row() -> dict[str, Any]:
    rows = _read_spool()
    assert len(rows) == 1
    return rows[0]


class _Unanswered(str):
    """Hermes Unanswered shape: a str subclass whose value is cancelled."""

    def __new__(cls) -> _Unanswered:
        return str.__new__(cls, "cancelled")


def test_approval_field_max_matches_server(ref: types.ModuleType) -> None:
    assert ref._APPROVAL_FIELD_MAX == _MAX_REASON_LEN


@pytest.mark.parametrize("choice", _CHOICES)
def test_post_records_choice(ref: types.ModuleType, choice: str) -> None:
    assert ref._post_approval_response(**_payload(choice=choice)) is None
    row = _only_row()
    assert row["event_type"] == "approval"
    assert row["phase"] == "response"
    assert row["choice"] == choice
    assert row["rule_id"] == "plugin_rule:destructive-recursive"


@pytest.mark.parametrize("choice", _CHOICES)
def test_pre_forces_choice_null(ref: types.ModuleType, choice: str) -> None:
    assert ref._pre_approval_request(**_payload(choice=choice)) is None
    row = _only_row()
    assert row["phase"] == "request"
    assert row["choice"] is None
    assert row["event_type"] == "approval"


def test_pre_without_choice_is_null(ref: types.ModuleType) -> None:
    assert ref._pre_approval_request(**_payload()) is None
    row = _only_row()
    assert row["phase"] == "request"
    assert row["choice"] is None


def test_post_empty_choice_stays_empty(ref: types.ModuleType) -> None:
    assert ref._post_approval_response(**_payload(choice="")) is None
    assert _only_row()["choice"] == ""


def test_payload_shape_on_request_and_response(ref: types.ModuleType) -> None:
    assert ref._pre_approval_request(**_payload(ignored_extra="nope")) is None
    assert ref._post_approval_response(**_payload(choice="once", ignored_extra="nope")) is None
    request, response = _read_spool()
    assert request["reason"] == "approval requested"
    assert response["reason"] == "approval response"
    for row in (request, response):
        assert row["tool"] == "terminal"
        assert row["session_id"] == "sess-id"
        assert row["session_key"] == "sess-key"
        assert row["surface"] == "cli"
        assert row["command"] == "<terminal> (plugin approval rule)"
        assert row["description"] == "run a command"
        assert row["tool_call_id"] == "tc-1"
        assert row["turn_id"] == "turn-1"
        assert row["pattern_keys"] == ["plugin_rule:destructive-recursive"]
        assert row["direction"] == "tool_call"
        assert row["param_scan_degraded"] is False
        assert row["tier"] is None
        assert row["severity"] is None
        assert row["bypassed_count"] is None
        assert row["coalesced"] is False
        assert row["armed"] is True
        assert str(row["scan_id"]).startswith("e-")
        assert "ignored_extra" not in row
    assert request["choice"] is None
    assert response["choice"] == "once"


def test_shell_command_has_empty_tool(ref: types.ModuleType) -> None:
    assert ref._post_approval_response(**_payload(command="rm -rf /tmp/x", choice="deny")) is None
    assert _only_row()["tool"] == ""


def test_session_id_wins_over_session_key(ref: types.ModuleType) -> None:
    assert (
        ref._post_approval_response(
            **_payload(session_id="from-hook", session_key="from-key", choice="once")
        )
        is None
    )
    row = _only_row()
    assert row["session_id"] == "from-hook"
    assert row["session_key"] == "from-key"


def test_empty_session_id_falls_back_to_session_key(ref: types.ModuleType) -> None:
    assert (
        ref._post_approval_response(
            **_payload(session_id="", session_key="from-key", choice="once")
        )
        is None
    )
    row = _only_row()
    assert row["session_id"] == "from-key"
    assert row["session_key"] == "from-key"


def test_command_and_pattern_keys_are_capped(ref: types.ModuleType) -> None:
    cap = ref._APPROVAL_FIELD_MAX
    long_key = "k" * (cap + 40)
    keys = [long_key, *([f"k{i}" for i in range(8)])]
    assert len(keys) == 9
    assert (
        ref._post_approval_response(
            **_payload(command="c" * (cap + 25), pattern_keys=keys, choice="deny")
        )
        is None
    )
    row = _only_row()
    assert row["command"] == "c" * cap
    assert len(row["command"]) == cap
    assert row["pattern_keys"] == [long_key[:cap], *[f"k{i}" for i in range(7)]]
    assert len(row["pattern_keys"]) == 8


def test_non_str_command_and_pattern_key_still_writes(ref: types.ModuleType) -> None:
    assert (
        ref._post_approval_response(
            **_payload(command={"not": "a str"}, pattern_keys=["keep", 3, None], choice="deny")
        )
        is None
    )
    row = _only_row()
    assert row["command"] == ""
    assert row["pattern_keys"] == ["keep"]


def test_unanswered_subclass_stores_cancelled(ref: types.ModuleType) -> None:
    assert ref._post_approval_response(**_payload(choice=_Unanswered())) is None
    assert _only_row()["choice"] == "cancelled"


def test_coalesced_only_boolean_true(ref: types.ModuleType) -> None:
    assert ref._pre_approval_request(**_payload(coalesced=True)) is None
    assert ref._pre_approval_request(**_payload(coalesced=1)) is None
    true_row, truthy_row = _read_spool()
    assert true_row["coalesced"] is True
    assert truthy_row["coalesced"] is False


def test_smart_decided_by_is_stored(ref: types.ModuleType) -> None:
    assert (
        ref._post_approval_response(
            **_payload(choice="smart_approve", decided_by="aux_llm", surface="smart")
        )
        is None
    )
    row = _only_row()
    assert row["decided_by"] == "aux_llm"
    assert row["choice"] == "smart_approve"
    assert row["surface"] == "smart"


def test_missing_keys_still_write(ref: types.ModuleType) -> None:
    assert ref._pre_approval_request() is None
    row = _only_row()
    assert row["event_type"] == "approval"
    assert row["phase"] == "request"
    assert row["choice"] is None
    assert row["command"] == ""
    assert row["rule_id"] == ""
    assert row["pattern_keys"] == []
    assert row["session_id"] == ""
    assert row["decided_by"] is None


def test_disarmed_still_writes_armed_false(
    ref: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ref, "_is_armed", lambda: False)
    assert ref._post_approval_response(**_payload(choice="deny")) is None
    row = _only_row()
    assert row["armed"] is False
    assert row["event_type"] == "approval"


def test_emit_raise_writes_nothing_and_skips_info(
    ref: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    before = _spool_bytes()

    def _boom(_event: dict[str, Any]) -> bool:
        raise RuntimeError("spool down")

    monkeypatch.setattr(ev, "emit_enforcement_event", _boom)
    with caplog.at_level(logging.DEBUG, logger="petasos.plugin"):
        assert ref._post_approval_response(**_payload(choice="deny")) is None
    assert _spool_bytes() == before
    assert not any(
        record.levelno == logging.INFO and "PETASOS_APPROVAL" in record.getMessage()
        for record in caplog.records
    )
    assert any(
        record.levelno == logging.DEBUG and "PETASOS_APPROVAL" in record.getMessage()
        for record in caplog.records
    )


def test_emit_false_writes_nothing_and_skips_info(
    ref: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    before = _spool_bytes()

    def _nope(_event: dict[str, Any]) -> bool:
        return False

    monkeypatch.setattr(ev, "emit_enforcement_event", _nope)
    with caplog.at_level(logging.DEBUG, logger="petasos.plugin"):
        assert ref._pre_approval_request(**_payload(choice="deny")) is None
    assert _spool_bytes() == before
    assert not any(
        record.levelno == logging.INFO and "PETASOS_APPROVAL" in record.getMessage()
        for record in caplog.records
    )
    assert any(
        record.levelno == logging.DEBUG and "PETASOS_APPROVAL" in record.getMessage()
        for record in caplog.records
    )


def test_success_log_omits_command_and_description(
    ref: types.ModuleType, caplog: pytest.LogCaptureFixture
) -> None:
    command = "<terminal> (plugin approval rule)"
    description = "DESC-SHOULD-NOT-LOG"
    with caplog.at_level(logging.INFO, logger="petasos.plugin"):
        assert (
            ref._post_approval_response(
                **_payload(command=command, description=description, choice="deny")
            )
            is None
        )
    infos = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.INFO and "PETASOS_APPROVAL" in record.getMessage()
    ]
    assert infos == [
        "PETASOS_APPROVAL phase=response choice=deny tool=terminal "
        "session_id=sess-id rule_id=plugin_rule:destructive-recursive surface=cli"
    ]
    assert command not in infos[0]
    assert description not in infos[0]


def test_register_binds_approval_hooks_once(
    ref: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_profile_rebind import _FakeCtx

    monkeypatch.setattr(ref, "_deferred_init", lambda: None)
    monkeypatch.setattr(ref, "_load_config", lambda res=None: {})
    ctx = _FakeCtx()
    ref.register(ctx)
    ref.register(ctx)
    assert ctx.registered.count("pre_approval_request") == 1
    assert ctx.registered.count("post_approval_response") == 1


def test_summary_approval_response_is_not_a_block() -> None:
    command = "c" * (_MAX_REASON_LEN + 25)
    summary = _enforcement_summary(
        {
            "event_type": "approval",
            "phase": "response",
            "choice": "deny",
            "rule_id": "plugin_rule:x",
            "tool": "terminal",
            "session_id": "sess",
            "command": command,
        }
    )
    assert summary["source"] == "enforcement"
    assert summary["safe"] is True
    assert summary["finding_count"] == 0
    assert summary["choice"] == "deny"
    assert summary["phase"] == "response"
    assert summary["rule_id"] == "plugin_rule:x"
    assert summary["tool"] == "terminal"
    assert summary["session_id"] == "sess"
    assert summary["command"] == command[:_MAX_REASON_LEN]
    assert "approval" not in _BLOCK_EVENT_TYPES


def test_summary_request_preserves_null_choice_and_caps_command() -> None:
    command = "z" * (_MAX_REASON_LEN + 10)
    summary = _enforcement_summary(
        {
            "event_type": "approval",
            "phase": "request",
            "choice": None,
            "command": command,
            "pattern_keys": "not-a-list",
        }
    )
    assert summary["choice"] is None
    assert summary["command"] == "z" * _MAX_REASON_LEN
    assert summary["pattern_keys"] is None
    listed = _enforcement_summary({"event_type": "approval", "pattern_keys": ["a", "b", 3]})
    assert listed["pattern_keys"] == ["a", "b", 3]
