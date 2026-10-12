"""PET-221: approve posture, once-per-session degraded approve, Hermes always."""

from __future__ import annotations

import concurrent.futures
import importlib.util
import inspect
import logging
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from petasos import (
    FrequencyTracker,
    GuardResult,
    PetasosConfig,
    Pipeline,
    ScanFinding,
    Severity,
)
from petasos.scanners.minimal import MinimalScanner
from petasos.session.formatting import format_block_message, format_content_block

_REF_PLUGIN_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "deployment"
    / "reference_plugin"
    / "__init__.py"
)
_DESTRUCTIVE = "petasos.syntactic.command.destructive-recursive"
_FETCH = "petasos.syntactic.command.fetch-exec"
_DEGRADED = "petasos.degraded"
_APPROVE_CMD = "Petasos asks for approval before running '{tool}'. Rule: {rule}."
_APPROVE_DEGRADED = (
    "Petasos asks for approval before running '{tool}'. "
    "Parameter scan is unreliable (petasos.degraded)."
)
_ALWAYS_WARN = "always-approval read unavailable; operator always will not waive Petasos blocks"


def _fake(name: str) -> Any:
    return types.ModuleType(name)


def _import_reference_plugin() -> Any:
    spec = importlib.util.spec_from_file_location(
        "petasos_reference_plugin_pet221", str(_REF_PLUGIN_PATH)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _finding(
    rule_id: str,
    *,
    finding_type: str = "command",
    severity: Severity = Severity.HIGH,
    confidence: float = 0.9,
    message: str = "finding",
) -> ScanFinding:
    return ScanFinding(
        rule_id=rule_id,
        finding_type=finding_type,
        severity=severity,
        confidence=confidence,
        message=message,
        scanner_name="minimal",
    )


def _guard(
    *,
    findings: tuple[ScanFinding, ...] = (),
    allowed: bool = True,
    tier: str = "none",
    reason: str = "allowed",
    degraded: bool = False,
) -> GuardResult:
    return GuardResult(
        allowed=allowed,
        reason=reason,
        findings=findings,
        tier=tier,
        param_scan_unsafe=bool(findings) or degraded,
        param_scan_degraded=degraded,
    )


def _pipeline(name: str, *, fail_mode: str = "degraded") -> Pipeline:
    return Pipeline(
        config=PetasosConfig(profile_name=name, fail_mode=fail_mode),  # type: ignore[arg-type]
        scanners=[MinimalScanner()],
    )


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
    tool: str,
    guard: GuardResult,
    *,
    profile: str | None = "code_generation",
    pipeline: Any = None,
    task_id: str = "s1",
    approve: bool = True,
    predicate: Any = None,
    args: dict[str, object] | None = None,
    yolo_env: str | None = None,
    yolo_session: bool | None = False,
) -> Any:
    if pipeline is not None:
        monkeypatch.setattr(ref, "_pipeline", pipeline)
    elif profile is not None:
        monkeypatch.setattr(ref, "_pipeline", _pipeline(profile))
    monkeypatch.setattr(ref, "_approve_directive_available", approve)
    if predicate is not None:
        monkeypatch.setattr(ref, "_rule_always_approved", predicate)
    if yolo_env is not None:
        monkeypatch.setenv("HERMES_YOLO_MODE", yolo_env)
    if yolo_session is None:
        monkeypatch.delitem(sys.modules, "tools.approval", raising=False)
        monkeypatch.delitem(sys.modules, "tools", raising=False)
    else:
        approval = _fake("tools.approval")
        approval.is_current_session_yolo_enabled = lambda: yolo_session
        _install_approval(monkeypatch, approval)
    monkeypatch.setattr(ref, "_run_async", lambda coro: guard)
    return ref._pre_tool_call(tool, {} if args is None else args, task_id=task_id)


def _false(_key: str) -> bool:
    return False


def _install_approval(monkeypatch: pytest.MonkeyPatch, module: Any) -> None:
    parent = _fake("tools")
    monkeypatch.setitem(sys.modules, "tools", parent)
    monkeypatch.setitem(sys.modules, "tools.approval", module)


class _RaisingSet(set[str]):
    def __contains__(self, item: object) -> bool:
        raise RuntimeError("membership")


# ---------------------------------------------------------------------------
# Pin A / Pin G contract seams. These do not monkeypatch the predicate.
# ---------------------------------------------------------------------------


def test_probe_approve_directive_with_fake_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = _import_reference_plugin()
    present = _fake("hermes_cli.plugins")
    present.get_pre_tool_call_directive = lambda: None
    monkeypatch.setitem(sys.modules, "hermes_cli", _fake("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.plugins", present)
    assert ref._probe_approve_directive() is True

    absent = _fake("hermes_cli.plugins")
    monkeypatch.setitem(sys.modules, "hermes_cli.plugins", absent)
    assert ref._probe_approve_directive() is False

    monkeypatch.delitem(sys.modules, "hermes_cli.plugins", raising=False)
    monkeypatch.delitem(sys.modules, "hermes_cli", raising=False)
    assert ref._probe_approve_directive() is False


def test_yolo_active_env_and_session_function(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = _import_reference_plugin()
    ref._approve_directive_available = True
    approval = _fake("tools.approval")
    approval.is_current_session_yolo_enabled = lambda: False
    _install_approval(monkeypatch, approval)

    monkeypatch.setenv("HERMES_YOLO_MODE", "")
    assert ref._yolo_active() is True

    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    assert ref._yolo_active() is False
    approval.is_current_session_yolo_enabled = lambda: True
    assert ref._yolo_active() is True

    ref._approve_directive_available = False
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    assert ref._yolo_active() is False


def test_yolo_active_import_failure_is_yolo(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = _import_reference_plugin()
    ref._approve_directive_available = True
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    monkeypatch.delitem(sys.modules, "tools.approval", raising=False)
    monkeypatch.delitem(sys.modules, "tools", raising=False)
    assert ref._yolo_active() is True


def test_rule_always_approved_set_membership() -> None:
    ref = _import_reference_plugin()
    approval = _fake("tools.approval")
    approval._permanent_approved = {_plugin(_DESTRUCTIVE)}
    sys.modules["tools.approval"] = approval
    try:
        assert ref._rule_always_approved(_DESTRUCTIVE) is True
        assert ref._rule_always_approved(_DEGRADED) is False
    finally:
        sys.modules.pop("tools.approval", None)


def test_rule_always_approved_fail_closed_shapes() -> None:
    ref = _import_reference_plugin()
    approval = _fake("tools.approval")
    approval._permanent_approved = [_plugin(_DESTRUCTIVE)]
    sys.modules["tools.approval"] = approval
    try:
        assert ref._rule_always_approved(_DESTRUCTIVE) is False
        del approval._permanent_approved
        assert ref._rule_always_approved(_DESTRUCTIVE) is False
        approval._permanent_approved = _RaisingSet([_plugin(_DESTRUCTIVE)])
        assert ref._rule_always_approved(_DESTRUCTIVE) is False
    finally:
        sys.modules.pop("tools.approval", None)
    assert ref._rule_always_approved(_DESTRUCTIVE) is False


def test_is_permanently_approved_wins_over_conflicting_set() -> None:
    ref = _import_reference_plugin()
    approval = _fake("tools.approval")
    approval._permanent_approved = set()

    def _is_permanently_approved(pattern_key: str) -> bool:
        return pattern_key == _plugin(_DESTRUCTIVE)

    approval._is_permanently_approved = _is_permanently_approved
    sys.modules["tools.approval"] = approval
    try:
        assert ref._rule_always_approved(_DESTRUCTIVE) is True
    finally:
        sys.modules.pop("tools.approval", None)


def test_raising_is_permanently_approved_is_false() -> None:
    ref = _import_reference_plugin()
    approval = _fake("tools.approval")
    approval._permanent_approved = {_plugin(_DESTRUCTIVE)}

    def _is_permanently_approved(_pattern_key: str) -> bool:
        raise RuntimeError("allowlist down")

    approval._is_permanently_approved = _is_permanently_approved
    sys.modules["tools.approval"] = approval
    try:
        assert ref._rule_always_approved(_DESTRUCTIVE) is False
    finally:
        sys.modules.pop("tools.approval", None)


def test_neither_always_read_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    ref = _import_reference_plugin()
    approval = _fake("tools.approval")
    approval._permanent_approved = ["not-a-set"]
    sys.modules["tools.approval"] = approval
    try:
        with caplog.at_level(logging.WARNING, logger="petasos.plugin"):
            assert ref._rule_always_approved(_DESTRUCTIVE) is False
            assert ref._rule_always_approved(_DEGRADED) is False
    finally:
        sys.modules.pop("tools.approval", None)
    warnings = [
        record.getMessage() for record in caplog.records if _ALWAYS_WARN in record.getMessage()
    ]
    assert warnings == [_ALWAYS_WARN]


def _plugin(rule_key: str) -> str:
    return "plugin_rule:" + rule_key


# ---------------------------------------------------------------------------
# Decision 14
# ---------------------------------------------------------------------------


def test_benign_dangerous_tool_is_allowed(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    assert _drive(monkeypatch, ref, "terminal", _guard(), predicate=_false) is None


def test_command_finding_approves(
    monkeypatch: pytest.MonkeyPatch, ref: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Hermes fails closed on deny, timeout, or no notifier (brief F17).

    Petasos does not observe that answer. The return that causes the host's
    fail-closed outcome is action=approve.
    """
    emitted: list[dict[str, Any]] = []

    def _record(**kw: Any) -> bool:
        emitted.append(kw)
        return True

    monkeypatch.setattr(ref, "_emit_enforcement_event", _record)
    with caplog.at_level(logging.INFO, logger="petasos.plugin"):
        out = _drive(
            monkeypatch,
            ref,
            "terminal",
            _guard(findings=(_finding(_DESTRUCTIVE),)),
            predicate=_false,
        )
    assert out == {
        "action": "approve",
        "rule_key": _DESTRUCTIVE,
        "message": _APPROVE_CMD.format(tool="terminal", rule=_DESTRUCTIVE),
    }
    assert "[BLOCKED by Petasos]" not in out["message"]
    assert emitted == []
    assert any("PETASOS_APPROVE" in record.getMessage() for record in caplog.records)


def test_worst_command_finding_is_the_rule_key(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    out = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(
            findings=(
                _finding(_FETCH, confidence=0.9),
                _finding(_DESTRUCTIVE, confidence=0.95),
            )
        ),
        predicate=_false,
    )
    assert out["action"] == "approve"
    assert out["rule_key"] == _DESTRUCTIVE


def test_approve_unavailable_blocks_both_paths(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    command = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(findings=(_finding(_DESTRUCTIVE),)),
        approve=False,
        predicate=_false,
    )
    degraded = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(degraded=True),
        approve=False,
        predicate=_false,
        task_id="s-no-directive",
    )
    for out, _findings in (
        (command, (_finding(_DESTRUCTIVE),)),
        (degraded, ()),
    ):
        assert out["action"] == "block"
        assert out["message"].startswith("[BLOCKED by Petasos]")
        assert "rule_key" not in out
    assert "NOT executed" in command["message"]
    assert degraded["message"] == format_content_block("degraded", "terminal", ())
    assert "s-no-directive" not in ref._degraded_approve_sessions


def test_yolo_env_blocks_unlisted_keys(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    command = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(findings=(_finding(_DESTRUCTIVE),)),
        predicate=_false,
        yolo_env="1",
        yolo_session=False,
    )
    degraded = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(degraded=True),
        predicate=_false,
        yolo_env="1",
        task_id="s-yolo-env",
    )
    assert command["action"] == "block" and "rule_key" not in command
    assert degraded["action"] == "block"
    assert "s-yolo-env" not in ref._degraded_approve_sessions


def test_yolo_session_flag_blocks_unlisted_keys(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    command = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(findings=(_finding(_DESTRUCTIVE),)),
        predicate=_false,
        yolo_session=True,
    )
    degraded = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(degraded=True),
        predicate=_false,
        task_id="s-yolo-session",
        yolo_session=True,
    )
    assert command["action"] == "block"
    assert degraded["action"] == "block"
    assert "s-yolo-session" not in ref._degraded_approve_sessions


def test_yolo_import_failure_blocks_unlisted_keys(
    monkeypatch: pytest.MonkeyPatch, ref: Any
) -> None:
    command = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(findings=(_finding(_DESTRUCTIVE),)),
        predicate=_false,
        yolo_session=None,
    )
    degraded = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(degraded=True),
        predicate=_false,
        task_id="s-yolo-import",
        yolo_session=None,
    )
    assert command["action"] == "block"
    assert degraded["action"] == "block"


def test_injection_blocks_with_and_without_degraded(
    monkeypatch: pytest.MonkeyPatch, ref: Any
) -> None:
    finding = _finding(
        "petasos.syntactic.injection.ignore-previous",
        finding_type="injection",
        message="injection finding",
    )
    for degraded in (False, True):
        out = _drive(
            monkeypatch,
            ref,
            "terminal",
            _guard(findings=(finding,), degraded=degraded),
            predicate=_false,
        )
        assert out["action"] == "block"
        assert "rule_key" not in out
        assert out["message"] == format_content_block("non_pii_param", "terminal", (finding,))
        assert "Parameter scan unavailable" not in out["message"]


def test_pii_egress_blocks_and_omits_degraded_reason(
    monkeypatch: pytest.MonkeyPatch, ref: Any
) -> None:
    finding = _finding("petasos.presidio.person", finding_type="pii", message="PII detected")
    for degraded in (False, True):
        out = _drive(
            monkeypatch,
            ref,
            "send_email",
            _guard(findings=(finding,), degraded=degraded),
            predicate=_false,
        )
        assert out["action"] == "block"
        assert out["message"] == format_content_block("pii_egress", "send_email", (finding,))
        assert "Parameter scan unavailable" not in out["message"]


def test_internal_pii_allows_or_approves_on_the_other_key(
    monkeypatch: pytest.MonkeyPatch, ref: Any
) -> None:
    pii = _finding("petasos.presidio.person", finding_type="pii")
    assert _drive(monkeypatch, ref, "terminal", _guard(findings=(pii,)), predicate=_false) is None
    command = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(findings=(pii, _finding(_DESTRUCTIVE))),
        predicate=_false,
    )
    assert command["action"] == "approve" and command["rule_key"] == _DESTRUCTIVE
    degraded = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(findings=(pii,), degraded=True),
        predicate=_false,
        task_id="s-pii-degraded",
    )
    assert degraded["rule_key"] == _DEGRADED


def test_source_taint_blocks_before_approve(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    class _Store:
        def tainted_source(self, session_id: str, args: dict[str, Any]) -> str:
            return "browser"

    monkeypatch.setattr(ref, "_source_taint_namespaces", frozenset({"browser"}))
    monkeypatch.setattr(ref, "_taint_store", _Store())
    for degraded, findings in (
        (False, ()),
        (True, ()),
        (True, (_finding(_DESTRUCTIVE),)),
    ):
        out = _drive(
            monkeypatch,
            ref,
            "send_email",
            _guard(findings=findings, degraded=degraded),
            predicate=_false,
        )
        assert out["action"] == "block"
        assert out["message"] == format_content_block("taint_egress", "send_email", ())


def test_block_posture_matches_todays_outcomes(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    injection = _finding("petasos.syntactic.injection.ignore-previous", finding_type="injection")
    pii = _finding("petasos.presidio.person", finding_type="pii")
    cases = (
        ("customer_service", "write_file", _guard(degraded=True), "block"),
        ("customer_service", "write_file", _guard(findings=(injection,)), "block"),
        ("customer_service", "send_email", _guard(findings=(pii,)), "block"),
        ("customer_service", "write_file", _guard(findings=(pii,)), None),
        ("customer_service", "read_file", _guard(degraded=True), None),
    )
    for profile, tool, guard, expect in cases:
        out = _drive(monkeypatch, ref, tool, guard, profile=profile, predicate=_false)
        if expect is None:
            assert out is None, (profile, tool)
        else:
            assert out["action"] == "block", (profile, tool)

    class _NoneProfile:
        default_profile = None

    out = _drive(
        monkeypatch,
        ref,
        "write_file",
        _guard(degraded=True),
        pipeline=_NoneProfile(),
        predicate=_false,
    )
    assert out["action"] == "block"

    tier3 = _guard(tier="tier3", allowed=False, reason="session terminated (tier3)")
    out = _drive(
        monkeypatch, ref, "read_file", tier3, profile="customer_service", predicate=_false
    )
    assert out["action"] == "block"
    assert out["message"] == format_block_message(tier3, "read_file")

    tier2 = _guard(allowed=False, tier="tier2", reason="tier2: tool calls blocked")
    out = _drive(
        monkeypatch, ref, "write_file", tier2, profile="customer_service", predicate=_false
    )
    assert out["action"] == "block"
    assert out["message"] == format_block_message(tier2, "write_file")


def test_missing_or_unrecognized_posture_blocks(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    out = _drive(
        monkeypatch,
        ref,
        "write_file",
        _guard(degraded=True),
        pipeline=object(),
        predicate=_false,
    )
    assert out["action"] == "block"

    class _Stub:
        def __init__(self, posture: object) -> None:
            self.dangerous_tool_posture = posture

    class _Pipe:
        def __init__(self, posture: object) -> None:
            self.default_profile = _Stub(posture)

    for posture in ("Approve", None):
        out = _drive(
            monkeypatch,
            ref,
            "write_file",
            _guard(degraded=True),
            pipeline=_Pipe(posture),
            predicate=_false,
        )
        assert out["action"] == "block"


def test_degraded_approve_once_per_session(
    monkeypatch: pytest.MonkeyPatch, ref: Any, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="petasos.plugin"):
        first = _drive(
            monkeypatch, ref, "terminal", _guard(degraded=True), predicate=_false, task_id="sess"
        )
    assert first["action"] == "approve"
    assert first["rule_key"] == _DEGRADED
    assert first["message"] == _APPROVE_DEGRADED.format(tool="terminal")
    assert "sess" in ref._degraded_approve_sessions
    assert any("PETASOS_APPROVE" in record.getMessage() for record in caplog.records)

    second = _drive(
        monkeypatch, ref, "terminal", _guard(degraded=True), predicate=_false, task_id="sess"
    )
    assert second is None

    injection = _finding("petasos.syntactic.injection.ignore-previous", finding_type="injection")
    blocked = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(findings=(injection,), degraded=True),
        predicate=_false,
        task_id="sess",
    )
    assert blocked["action"] == "block"
    assert blocked["message"] == format_content_block("non_pii_param", "terminal", (injection,))

    commanded = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(findings=(_finding(_DESTRUCTIVE),), degraded=True),
        predicate=_false,
        task_id="sess",
    )
    assert commanded["action"] == "approve"
    assert commanded["rule_key"] == _DESTRUCTIVE


def test_recorded_session_blocks_again_under_yolo_or_block_posture(
    monkeypatch: pytest.MonkeyPatch, ref: Any
) -> None:
    first = _drive(
        monkeypatch, ref, "terminal", _guard(degraded=True), predicate=_false, task_id="again"
    )
    assert first["rule_key"] == _DEGRADED
    yolo = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(degraded=True),
        predicate=_false,
        task_id="again",
        yolo_session=True,
    )
    assert yolo["action"] == "block"

    pipe = _pipeline("code_generation")
    recorded = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(degraded=True),
        pipeline=pipe,
        predicate=_false,
        task_id="rebind",
    )
    assert recorded["rule_key"] == _DEGRADED
    pipe.reconfigure(PetasosConfig(profile_name="customer_service"))
    assert pipe.default_profile is not None
    assert pipe.default_profile.dangerous_tool_posture == "block"
    rebound = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(degraded=True),
        pipeline=pipe,
        predicate=_false,
        task_id="rebind",
    )
    assert rebound["action"] == "block"


def test_block_posture_does_not_record_and_later_approve_still_prompts(
    monkeypatch: pytest.MonkeyPatch, ref: Any
) -> None:
    blocked = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(degraded=True),
        profile="customer_service",
        predicate=_false,
        task_id="later",
    )
    assert blocked["action"] == "block"
    assert "later" not in ref._degraded_approve_sessions
    later = _drive(
        monkeypatch, ref, "terminal", _guard(degraded=True), predicate=_false, task_id="later"
    )
    assert later["action"] == "approve" and later["rule_key"] == _DEGRADED


def test_anonymous_calls_each_approve(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    first = ref_call(monkeypatch, ref)
    second = ref_call(monkeypatch, ref)
    assert first["rule_key"] == _DEGRADED and second["rule_key"] == _DEGRADED
    anon = {sid for sid in ref._degraded_approve_sessions if sid.startswith("anon-")}
    assert len(anon) == 2


def ref_call(monkeypatch: pytest.MonkeyPatch, ref: Any) -> Any:
    approval = _fake("tools.approval")
    approval.is_current_session_yolo_enabled = lambda: False
    _install_approval(monkeypatch, approval)
    monkeypatch.setattr(ref, "_pipeline", _pipeline("code_generation"))
    monkeypatch.setattr(ref, "_approve_directive_available", True)
    monkeypatch.setattr(ref, "_rule_always_approved", _false)
    monkeypatch.setattr(ref, "_run_async", lambda coro: _guard(degraded=True))
    return ref._pre_tool_call("terminal", {"text": "x"})


def test_hook_error_degraded_approve_and_block(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    guard = _guard(degraded=True)
    approved = _drive(monkeypatch, ref, "terminal", guard, predicate=_false, task_id="hook")
    assert approved["rule_key"] == _DEGRADED
    assert "Parameter scan is unreliable" in approved["message"]
    blocked = _drive(
        monkeypatch,
        ref,
        "terminal",
        guard,
        profile="customer_service",
        predicate=_false,
        task_id="hook-cs",
    )
    assert blocked["action"] == "block"
    opened = _drive(
        monkeypatch,
        ref,
        "terminal",
        guard,
        pipeline=_pipeline("code_generation", fail_mode="open"),
        predicate=_false,
        task_id="hook-open",
    )
    assert opened["rule_key"] == _DEGRADED
    opened_block = _drive(
        monkeypatch,
        ref,
        "terminal",
        guard,
        pipeline=_pipeline("customer_service", fail_mode="open"),
        predicate=_false,
        task_id="hook-open-cs",
    )
    assert opened_block["action"] == "block"


def test_always_on_one_command_key_leaves_the_other(
    monkeypatch: pytest.MonkeyPatch, ref: Any
) -> None:
    def predicate(rule_key: str) -> bool:
        return rule_key == _DESTRUCTIVE

    out = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(findings=(_finding(_DESTRUCTIVE), _finding(_FETCH, confidence=0.9))),
        predicate=predicate,
    )
    assert out["action"] == "approve" and out["rule_key"] == _FETCH
    yolo = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(findings=(_finding(_DESTRUCTIVE), _finding(_FETCH, confidence=0.9))),
        predicate=predicate,
        yolo_session=True,
    )
    assert yolo["action"] == "block"
    assert "fetch-exec" in yolo["message"]


def test_always_approved_keys_return_none(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    def command_only(rule_key: str) -> bool:
        return rule_key == _DESTRUCTIVE

    def degraded_only(rule_key: str) -> bool:
        return rule_key == _DEGRADED

    assert (
        _drive(
            monkeypatch,
            ref,
            "terminal",
            _guard(findings=(_finding(_DESTRUCTIVE),)),
            predicate=command_only,
        )
        is None
    )
    assert (
        _drive(
            monkeypatch,
            ref,
            "terminal",
            _guard(findings=(_finding(_DESTRUCTIVE),)),
            predicate=command_only,
            yolo_session=True,
        )
        is None
    )
    assert (
        _drive(
            monkeypatch,
            ref,
            "terminal",
            _guard(degraded=True),
            predicate=degraded_only,
            task_id="always-deg",
        )
        is None
    )
    assert "always-deg" not in ref._degraded_approve_sessions
    assert (
        _drive(
            monkeypatch,
            ref,
            "terminal",
            _guard(degraded=True),
            profile="customer_service",
            predicate=degraded_only,
            task_id="always-cs",
        )
        is None
    )
    injection = _finding("petasos.syntactic.injection.ignore-previous", finding_type="injection")
    blocked = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(findings=(injection,), degraded=True),
        predicate=degraded_only,
    )
    assert blocked["action"] == "block"
    stepped = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(findings=(_finding(_DESTRUCTIVE),), degraded=True),
        predicate=degraded_only,
    )
    assert stepped["action"] == "approve" and stepped["rule_key"] == _DESTRUCTIVE
    customer_command = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(findings=(_finding(_DESTRUCTIVE), _finding(_FETCH))),
        profile="customer_service",
        predicate=command_only,
    )
    assert customer_command["action"] == "block"
    assert "fetch-exec" in customer_command["message"]
    assert (
        _drive(
            monkeypatch,
            ref,
            "terminal",
            _guard(findings=(_finding(_DESTRUCTIVE),)),
            profile="customer_service",
            predicate=command_only,
        )
        is None
    )


def test_raising_predicate_is_treated_as_false(monkeypatch: pytest.MonkeyPatch, ref: Any) -> None:
    def boom(_rule_key: str) -> bool:
        raise RuntimeError("predicate down")

    out = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(findings=(_finding(_DESTRUCTIVE),)),
        predicate=boom,
    )
    assert out["action"] == "approve" and out["rule_key"] == _DESTRUCTIVE
    blocked = _drive(
        monkeypatch,
        ref,
        "terminal",
        _guard(degraded=True),
        profile="customer_service",
        predicate=boom,
    )
    assert blocked["action"] == "block"


def test_tier2_is_not_waived_by_always_or_approve(
    monkeypatch: pytest.MonkeyPatch, ref: Any
) -> None:
    guard = _guard(
        allowed=False,
        tier="tier2",
        reason="tier2: tool calls blocked",
        findings=(_finding(_DESTRUCTIVE),),
        degraded=True,
    )

    def always(_rule_key: str) -> bool:
        return True

    out = _drive(monkeypatch, ref, "write_file", guard, predicate=always)
    assert out == {
        "action": "block",
        "message": format_block_message(guard, "write_file"),
    }


def test_cold_window_does_not_read_posture_or_always(
    monkeypatch: pytest.MonkeyPatch, ref: Any
) -> None:
    seen: list[str] = []

    def predicate(rule_key: str) -> bool:
        seen.append(rule_key)
        return True

    monkeypatch.setattr(ref, "_initialized", False)
    monkeypatch.setattr(ref, "_ensure_initialized", lambda: False)
    monkeypatch.setattr(ref, "_config", {"fail_mode": "degraded"})
    monkeypatch.setattr(ref, "_pipeline", _pipeline("code_generation"))
    monkeypatch.setattr(ref, "_approve_directive_available", True)
    monkeypatch.setattr(ref, "_rule_always_approved", predicate)
    ref._degraded_approve_sessions.add("cold")

    def _fallback(tool_name: str, args: dict[str, Any], task_id: str, **kwargs: Any) -> None:
        ref._fallback_state.outcome = "clean"
        return None

    monkeypatch.setattr(ref, "_fallback_pre_tool_call", _fallback)
    out = ref._pre_tool_call("write_file", {"text": "ok"}, task_id="cold")
    assert out is not None and out["action"] == "block"
    assert seen == []


def test_disabled_scanners_validation() -> None:
    with pytest.raises(ValueError, match="nope"):
        PetasosConfig(disabled_scanners=("nope",))
    with pytest.raises(ValueError, match="not a string"):
        PetasosConfig(disabled_scanners="llm_guard")  # type: ignore[arg-type]


def test_pet224_timeout_and_error_never_approve(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    ref = _import_reference_plugin()
    if "evaluation_timeout" not in inspect.getsource(ref._pre_tool_call):
        pytest.skip("PET-224 guard-evaluation arm is not on this tree yet")
    monkeypatch.setattr(ref, "_initialized", True)
    monkeypatch.setattr(ref, "_init_error", None)
    monkeypatch.setattr(ref, "_is_armed", lambda: True)
    monkeypatch.setattr(ref, "_maybe_reconfigure", lambda: None)
    monkeypatch.setattr(ref, "_pipeline", _pipeline("code_generation"))
    monkeypatch.setattr(ref, "_approve_directive_available", True)
    monkeypatch.setattr(ref, "_rule_always_approved", lambda _key: True)
    monkeypatch.setattr(ref, "_lineage_registry", None)
    monkeypatch.setattr(ref, "_frequency_tracker", FrequencyTracker(PetasosConfig()))
    ref._degraded_approve_sessions.add("s-224")
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)

    def _raise(exc: BaseException) -> Any:
        def _run(_coro: Any, timeout: float = 15) -> Any:
            raise exc

        return _run

    for exc, reason in (
        (concurrent.futures.TimeoutError(), "guard evaluation unavailable: evaluation_timeout"),
        (RuntimeError("down"), "guard evaluation unavailable: evaluation_error"),
    ):
        emitted: list[dict[str, Any]] = []

        def _emit(bucket: list[dict[str, Any]] = emitted, **kw: Any) -> bool:
            bucket.append(kw)
            return True

        monkeypatch.setattr(ref, "_emit_enforcement_event", _emit)
        monkeypatch.setattr(ref, "_run_async", _raise(exc))
        with caplog.at_level(logging.INFO, logger="petasos.plugin"):
            out = ref._pre_tool_call("write_file", {"path": "a.txt"}, task_id="s-224")
        assert out is not None and out["action"] == "block"
        quarantines = [event for event in emitted if event.get("event_type") == "quarantine"]
        assert len(quarantines) == 1
        assert quarantines[0]["reason"] == reason
        assert not any(event.get("event_type") == "tier3" for event in emitted)
        assert not any("PETASOS_APPROVE" in record.getMessage() for record in caplog.records)
        caplog.clear()
