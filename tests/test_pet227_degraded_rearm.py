"""PET-227: record a degraded approve only after Hermes confirms it.

Handlers are called directly. No live Hermes process. The spool is the
conftest-isolated temp file. Helpers are local: this module does not import
the PET-221 fixtures.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

import petasos.console._events as ev
from petasos import GuardResult, PetasosConfig, Pipeline, ScanFinding, Severity
from petasos.scanners.minimal import MinimalScanner

_REF_PLUGIN_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "deployment"
    / "reference_plugin"
    / "__init__.py"
)
_DEGRADED = "petasos.degraded"
_DESTRUCTIVE = "petasos.syntactic.command.destructive-recursive"
_PATTERN = "plugin_rule:petasos.degraded"


def _import_reference_plugin() -> Any:
    spec = importlib.util.spec_from_file_location(
        "petasos_reference_plugin_pet227", str(_REF_PLUGIN_PATH)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _finding(rule_id: str) -> ScanFinding:
    return ScanFinding(
        rule_id=rule_id,
        finding_type="command",
        severity=Severity.HIGH,
        confidence=0.9,
        message="finding",
        scanner_name="minimal",
    )


def _guard(
    *,
    findings: tuple[ScanFinding, ...] = (),
    degraded: bool = False,
) -> GuardResult:
    return GuardResult(
        allowed=True,
        reason="allowed",
        findings=findings,
        tier="none",
        param_scan_unsafe=bool(findings) or degraded,
        param_scan_degraded=degraded,
    )


def _pipeline(name: str) -> Pipeline:
    return Pipeline(
        config=PetasosConfig(profile_name=name, fail_mode="degraded"),
        scanners=[MinimalScanner()],
    )


def _install_approval(monkeypatch: pytest.MonkeyPatch, yolo: bool) -> None:
    parent = types.ModuleType("tools")
    approval = types.ModuleType("tools.approval")
    approval.is_current_session_yolo_enabled = lambda: yolo  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tools", parent)
    monkeypatch.setitem(sys.modules, "tools.approval", approval)


@pytest.fixture
def ref(monkeypatch: pytest.MonkeyPatch) -> Any:
    mod = _import_reference_plugin()
    monkeypatch.setattr(mod, "_initialized", True)
    monkeypatch.setattr(mod, "_init_error", None)
    monkeypatch.setattr(mod, "_is_armed", lambda: True)
    monkeypatch.setattr(mod, "_maybe_reconfigure", lambda: None)
    monkeypatch.setattr(mod, "_egress_sink_tools", frozenset({"send_email"}))
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    mod._reset_degraded_approve_sessions()
    return mod


def _drive(
    monkeypatch: pytest.MonkeyPatch,
    ref: Any,
    guard: GuardResult,
    *,
    task_id: str = "sess",
    session_id: object = "hs-1",
    turn_id: object = "turn-1",
    tool_call_id: object = "tc-1",
    profile: str | None = "code_generation",
    yolo: bool = False,
) -> Any:
    if profile is not None:
        monkeypatch.setattr(ref, "_pipeline", _pipeline(profile))
    monkeypatch.setattr(ref, "_approve_directive_available", True)
    monkeypatch.setattr(ref, "_rule_always_approved", lambda _key: False)
    _install_approval(monkeypatch, yolo)
    monkeypatch.setattr(ref, "_run_async", lambda coro: guard)
    return ref._pre_tool_call(
        "terminal",
        {"text": "x"},
        task_id=task_id,
        session_id=session_id,
        turn_id=turn_id,
        tool_call_id=tool_call_id,
    )


def _post(
    ref: Any,
    choice: object,
    *,
    session_id: object = "hs-1",
    turn_id: object = "turn-1",
    tool_call_id: object = "tc-1",
    pattern_key: str = _PATTERN,
) -> Any:
    return ref._post_approval_response(
        pattern_key=pattern_key,
        choice=choice,
        session_id=session_id,
        turn_id=turn_id,
        tool_call_id=tool_call_id,
    )


def _key(
    session_id: str = "hs-1",
    turn_id: str = "turn-1",
    tool_call_id: str = "tc-1",
) -> tuple[str, str, str]:
    return (session_id, turn_id, tool_call_id)


def _assert_degraded(out: Any) -> None:
    assert isinstance(out, dict)
    assert out["action"] == "approve"
    assert out["rule_key"] == _DEGRADED


def _read_spool() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        with open(ev._spool_path(), encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                loaded = json.loads(stripped)
                assert isinstance(loaded, dict)
                out.append(loaded)
    except FileNotFoundError:
        return []
    return out


def test_session_records_and_suppresses_the_next_call(
    monkeypatch: pytest.MonkeyPatch, ref: Any
) -> None:
    first = _drive(monkeypatch, ref, _guard(degraded=True))
    _assert_degraded(first)
    assert "sess" not in ref._degraded_approve_sessions
    assert ref._degraded_approve_pending[_key()] == "sess"
    assert _post(ref, "session") is None
    assert "sess" in ref._degraded_approve_sessions
    assert _key() not in ref._degraded_approve_pending
    second = _drive(monkeypatch, ref, _guard(degraded=True), tool_call_id="tc-2")
    assert second is None
    assert _key(tool_call_id="tc-2") not in ref._degraded_approve_pending


def test_always_records_and_suppresses_the_next_call(
    monkeypatch: pytest.MonkeyPatch, ref: Any
) -> None:
    first = _drive(monkeypatch, ref, _guard(degraded=True))
    _assert_degraded(first)
    assert "sess" not in ref._degraded_approve_sessions
    assert _post(ref, "always") is None
    assert "sess" in ref._degraded_approve_sessions
    second = _drive(monkeypatch, ref, _guard(degraded=True), tool_call_id="tc-2")
    assert second is None


def test_deny_rearms(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    _assert_degraded(_drive(monkeypatch, ref, _guard(degraded=True)))
    assert _post(ref, "deny") is None
    assert "sess" not in ref._degraded_approve_sessions
    assert _key() not in ref._degraded_approve_pending
    again = _drive(monkeypatch, ref, _guard(degraded=True), tool_call_id="tc-2")
    _assert_degraded(again)
    assert ref._degraded_approve_pending[_key(tool_call_id="tc-2")] == "sess"


def test_timeout_rearms(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    _assert_degraded(_drive(monkeypatch, ref, _guard(degraded=True)))
    assert _post(ref, "timeout") is None
    assert "sess" not in ref._degraded_approve_sessions
    again = _drive(monkeypatch, ref, _guard(degraded=True), tool_call_id="tc-2")
    _assert_degraded(again)


def test_once_rearms(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    _assert_degraded(_drive(monkeypatch, ref, _guard(degraded=True)))
    assert _post(ref, "once") is None
    assert "sess" not in ref._degraded_approve_sessions
    assert _key() not in ref._degraded_approve_pending
    again = _drive(monkeypatch, ref, _guard(degraded=True), tool_call_id="tc-2")
    _assert_degraded(again)


@pytest.mark.parametrize(
    "choice",
    ["cancelled", "notify_failed", "smart_approve", "", None],
)
def test_other_non_confirming_choices_rearm(
    monkeypatch: pytest.MonkeyPatch, ref: Any, choice: str | None
) -> None:
    ref._degraded_approve_sessions.add("kept")
    _assert_degraded(_drive(monkeypatch, ref, _guard(degraded=True)))
    before = set(ref._degraded_approve_sessions)
    assert "sess" not in before
    assert _post(ref, choice) is None
    assert set(ref._degraded_approve_sessions) == before
    assert _key() not in ref._degraded_approve_pending


def test_no_post_keeps_reprompting(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    _assert_degraded(_drive(monkeypatch, ref, _guard(degraded=True), tool_call_id="tc-1"))
    _assert_degraded(_drive(monkeypatch, ref, _guard(degraded=True), tool_call_id="tc-2"))
    assert ref._degraded_approve_sessions == set()
    assert ref._degraded_approve_pending[_key(tool_call_id="tc-1")] == "sess"
    assert ref._degraded_approve_pending[_key(tool_call_id="tc-2")] == "sess"


def test_empty_tool_call_id_is_not_stored(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    _assert_degraded(_drive(monkeypatch, ref, _guard(degraded=True), tool_call_id=""))
    assert ref._degraded_approve_pending == {}
    assert _post(ref, "session", tool_call_id="") is None
    assert "sess" not in ref._degraded_approve_sessions


def test_non_str_tool_call_id_is_not_stored(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    _assert_degraded(_drive(monkeypatch, ref, _guard(degraded=True), tool_call_id=7))
    assert ref._degraded_approve_pending == {}
    assert _post(ref, "session", tool_call_id=7) is None
    assert "sess" not in ref._degraded_approve_sessions


def test_other_pattern_does_not_pop(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    _assert_degraded(_drive(monkeypatch, ref, _guard(degraded=True)))
    assert (
        _post(
            ref,
            "session",
            pattern_key="plugin_rule:petasos.syntactic.command.destructive-recursive",
        )
        is None
    )
    assert ref._degraded_approve_pending[_key()] == "sess"
    assert "sess" not in ref._degraded_approve_sessions


def test_unknown_tool_call_id_does_not_record(ref: Any) -> None:
    assert _post(ref, "session", tool_call_id="never-noted") is None
    assert ref._degraded_approve_sessions == set()
    assert ref._degraded_approve_pending == {}


def test_later_deny_does_not_unrecord(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    _assert_degraded(_drive(monkeypatch, ref, _guard(degraded=True), tool_call_id="tc-a"))
    _assert_degraded(_drive(monkeypatch, ref, _guard(degraded=True), tool_call_id="tc-b"))
    assert _post(ref, "session", tool_call_id="tc-a") is None
    assert _post(ref, "deny", tool_call_id="tc-b") is None
    assert "sess" in ref._degraded_approve_sessions
    assert _key(tool_call_id="tc-b") not in ref._degraded_approve_pending


def test_cross_session_same_tool_call_id_does_not_cross_record(
    monkeypatch: pytest.MonkeyPatch, ref: Any
) -> None:
    _assert_degraded(
        _drive(
            monkeypatch,
            ref,
            _guard(degraded=True),
            task_id="sess-a",
            session_id="hs-a",
            turn_id="turn-shared",
            tool_call_id="call_0",
        )
    )
    _assert_degraded(
        _drive(
            monkeypatch,
            ref,
            _guard(degraded=True),
            task_id="sess-b",
            session_id="hs-b",
            turn_id="turn-shared",
            tool_call_id="call_0",
        )
    )
    assert (
        _post(ref, "session", session_id="hs-a", turn_id="turn-shared", tool_call_id="call_0")
        is None
    )
    assert (
        _post(ref, "deny", session_id="hs-b", turn_id="turn-shared", tool_call_id="call_0") is None
    )
    assert "sess-a" in ref._degraded_approve_sessions
    assert "sess-b" not in ref._degraded_approve_sessions
    assert _key("hs-a", "turn-shared", "call_0") not in ref._degraded_approve_pending
    assert _key("hs-b", "turn-shared", "call_0") not in ref._degraded_approve_pending


def test_unrecorded_degraded_with_command_prompts_as_degraded(
    monkeypatch: pytest.MonkeyPatch, ref: Any
) -> None:
    out = _drive(
        monkeypatch,
        ref,
        _guard(findings=(_finding(_DESTRUCTIVE),), degraded=True),
    )
    _assert_degraded(out)
    assert ref._degraded_approve_pending[_key()] == "sess"


def test_record_survives_emit_false(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    _assert_degraded(_drive(monkeypatch, ref, _guard(degraded=True)))

    def _nope(_event: dict[str, Any]) -> bool:
        return False

    monkeypatch.setattr(ev, "emit_enforcement_event", _nope)
    assert _post(ref, "session") is None
    assert "sess" in ref._degraded_approve_sessions


def test_record_survives_emit_raise(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    _assert_degraded(_drive(monkeypatch, ref, _guard(degraded=True)))

    def _boom(_event: dict[str, Any]) -> bool:
        raise RuntimeError("spool down")

    monkeypatch.setattr(ev, "emit_enforcement_event", _boom)
    assert _post(ref, "session") is None
    assert "sess" in ref._degraded_approve_sessions


def test_apply_raise_still_emits(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    _assert_degraded(_drive(monkeypatch, ref, _guard(degraded=True)))

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("apply down")

    monkeypatch.setattr(ref, "_apply_degraded_approve_response", _boom)
    assert _post(ref, "session") is None
    approval = [row for row in _read_spool() if row.get("event_type") == "approval"]
    assert len(approval) == 1
    assert approval[0]["phase"] == "response"
    assert approval[0]["choice"] == "session"
    assert "sess" not in ref._degraded_approve_sessions


def test_pre_hook_does_not_record(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    _assert_degraded(_drive(monkeypatch, ref, _guard(degraded=True)))
    pending_before = dict(ref._degraded_approve_pending)
    sessions_before = set(ref._degraded_approve_sessions)
    assert (
        ref._pre_approval_request(
            pattern_key=_PATTERN,
            choice="session",
            session_id="hs-1",
            turn_id="turn-1",
            tool_call_id="tc-1",
        )
        is None
    )
    assert dict(ref._degraded_approve_pending) == pending_before
    assert set(ref._degraded_approve_sessions) == sessions_before


def test_pending_drops_oldest(ref: Any) -> None:
    cap = ref._MAX_DEGRADED_PENDING
    ref._note_degraded_approve_pending("sess-0", "hs-drop", "turn-drop", "tc-0")
    for index in range(1, cap + 1):
        ref._note_degraded_approve_pending(
            "sess-" + str(index), "hs-drop", "turn-drop", f"tc-{index}"
        )
    assert len(ref._degraded_approve_pending) == cap
    assert _key("hs-drop", "turn-drop", "tc-0") not in ref._degraded_approve_pending
    assert ref._degraded_approve_pending[_key("hs-drop", "turn-drop", "tc-1")] == "sess-1"
    assert (
        _post(ref, "session", session_id="hs-drop", turn_id="turn-drop", tool_call_id="tc-0")
        is None
    )
    assert "sess-0" not in ref._degraded_approve_sessions
    assert (
        _post(ref, "session", session_id="hs-drop", turn_id="turn-drop", tool_call_id="tc-1")
        is None
    )
    assert "sess-1" in ref._degraded_approve_sessions


def test_disarmed_confirm_records(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    _assert_degraded(_drive(monkeypatch, ref, _guard(degraded=True)))
    monkeypatch.setattr(ref, "_is_armed", lambda: False)
    assert _post(ref, "session") is None
    assert "sess" in ref._degraded_approve_sessions
    monkeypatch.setattr(ref, "_is_armed", lambda: True)
    second = _drive(monkeypatch, ref, _guard(degraded=True), tool_call_id="tc-2")
    assert second is None


def test_recorded_session_blocks_under_yolo_and_block(
    monkeypatch: pytest.MonkeyPatch, ref: Any
) -> None:
    _assert_degraded(_drive(monkeypatch, ref, _guard(degraded=True)))
    assert _post(ref, "session") is None
    yolo = _drive(monkeypatch, ref, _guard(degraded=True), tool_call_id="tc-yolo", yolo=True)
    assert isinstance(yolo, dict)
    assert yolo["action"] == "block"
    blocked = _drive(
        monkeypatch,
        ref,
        _guard(degraded=True),
        tool_call_id="tc-block",
        profile="customer_service",
    )
    assert isinstance(blocked, dict)
    assert blocked["action"] == "block"
    assert "sess" in ref._degraded_approve_sessions


def test_confirmed_anon_does_not_cover_the_next_anon(
    monkeypatch: pytest.MonkeyPatch, ref: Any
) -> None:
    first = _drive(monkeypatch, ref, _guard(degraded=True), task_id="", tool_call_id="tc-anon")
    _assert_degraded(first)
    noted = ref._degraded_approve_pending[_key(tool_call_id="tc-anon")]
    assert isinstance(noted, str)
    assert noted.startswith("anon-")
    assert len(noted) == len("anon-") + 8
    assert _post(ref, "session", tool_call_id="tc-anon") is None
    assert noted in ref._degraded_approve_sessions
    second = _drive(monkeypatch, ref, _guard(degraded=True), task_id="", tool_call_id="tc-anon-2")
    _assert_degraded(second)
    minted = ref._degraded_approve_pending[_key(tool_call_id="tc-anon-2")]
    assert minted.startswith("anon-")
    assert minted != noted


def test_command_approve_does_not_note(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    out = _drive(monkeypatch, ref, _guard(findings=(_finding(_DESTRUCTIVE),)))
    assert isinstance(out, dict)
    assert out["action"] == "approve"
    assert out["rule_key"] == _DESTRUCTIVE
    assert ref._degraded_approve_pending == {}
    assert "sess" not in ref._degraded_approve_sessions


def test_reset_clears_both(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    _assert_degraded(_drive(monkeypatch, ref, _guard(degraded=True), tool_call_id="tc-1"))
    _assert_degraded(_drive(monkeypatch, ref, _guard(degraded=True), tool_call_id="tc-2"))
    assert _post(ref, "session", tool_call_id="tc-1") is None
    assert "sess" in ref._degraded_approve_sessions
    assert _key(tool_call_id="tc-2") in ref._degraded_approve_pending
    ref._reset_degraded_approve_sessions()
    assert ref._degraded_approve_sessions == set()
    assert ref._degraded_approve_pending == {}
