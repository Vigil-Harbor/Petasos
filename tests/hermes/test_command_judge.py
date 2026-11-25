"""The Hermes predicate, with the host modules stood in.

Each test turns one condition off. The live gate is pinned in
``tests/hermes_host/test_command_judge.py``.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from petasos.enforce import CommandJudge
from petasos.hermes.host import command_judge

_COMMAND = "rm -rf /tmp/petasos-not-real"


def _install(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    detection = types.ModuleType("tools.approval_detection")
    detect = overrides.get("detect", lambda _command: (True, "delete", "delete"))
    if detect is not None:
        detection.detect_dangerous_command = detect  # type: ignore[attr-defined]
    approval = types.ModuleType("tools.approval")
    approval._should_skip_container_guards = overrides.get(  # type: ignore[attr-defined]
        "skip", lambda _env, has_host_access=False: False
    )
    approval._floor_block = overrides.get(  # type: ignore[attr-defined]
        "floor", lambda _command, sudo_guard=False: None
    )
    approval._yolo_active = overrides.get("yolo", lambda: False)  # type: ignore[attr-defined]
    approval._command_matches_permanent_allowlist = overrides.get(  # type: ignore[attr-defined]
        "allow", lambda _command: False
    )
    approval._presence = overrides.get(  # type: ignore[attr-defined]
        "presence", lambda _callback=None: (None, True, False, False)
    )
    approval._command_findings = overrides.get(  # type: ignore[attr-defined]
        "findings", lambda _command: [("delete", "delete")]
    )
    approval._approval_scope = overrides.get(  # type: ignore[attr-defined]
        "scope", lambda _session, _key: None
    )
    approval.get_current_session_key = lambda default="default": "s"  # type: ignore[attr-defined]
    approval._pending_findings = overrides.get(  # type: ignore[attr-defined]
        "pending",
        lambda findings, _approved: (["delete"], "delete") if findings else None,
    )
    terminal = types.ModuleType("tools.terminal_tool")
    terminal._get_env_config = overrides.get(  # type: ignore[attr-defined]
        "config", lambda: {"env_type": overrides.get("env_type", "local")}
    )
    terminal._docker_has_host_access = overrides.get(  # type: ignore[attr-defined]
        "access", lambda _config: False
    )
    context = types.ModuleType("tools.approval_context")
    context._get_approval_mode = overrides.get("mode", lambda: "manual")  # type: ignore[attr-defined]
    modules = {
        "tools": types.ModuleType("tools"),
        "tools.approval_detection": detection,
        "tools.approval": approval,
        "tools.approval_context": context,
        "tools.terminal_tool": terminal,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("manual", CommandJudge.PERSON),
        ("smart", CommandJudge.GUARDIAN),
        ("off", CommandJudge.NOBODY),
    ],
)
def test_a_flagged_command_with_a_person_present_has_a_judge(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected: CommandJudge,
) -> None:
    _install(monkeypatch, mode=lambda: mode)
    assert command_judge(_COMMAND) is expected


@pytest.mark.parametrize("mode", ["manual", "smart"])
def test_each_host_fact_that_means_nobody_is_asked_answers_no(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    cases: list[tuple[str, dict[str, Any]]] = [
        ("not flagged", {"detect": lambda _command: (False, None, None)}),
        ("raises", {"detect": _raise}),
        ("missing detector", {"detect": None}),
        ("container", {"skip": lambda _env, has_host_access=False: True}),
        ("hardline", {"floor": lambda _command, sudo_guard=False: {"approved": False}}),
        ("mode off", {"mode": lambda: "off"}),
        ("unknown mode", {"mode": lambda: "approve"}),
        ("yolo", {"yolo": lambda: True}),
        ("allowlist", {"allow": lambda _command: True}),
        ("headless", {"presence": lambda _callback=None: (None, False, False, False)}),
        ("already approved", {"pending": lambda _findings, _approved: None}),
        ("backend moved", {"config": _raise}),
    ]
    for name, overrides in cases:
        _install(monkeypatch, **({"mode": lambda: mode} | overrides))
        assert command_judge(_COMMAND) is CommandJudge.NOBODY, name


def test_a_missing_hermes_answers_no(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("petasos.hermes.host.load_module", lambda _name: None)
    assert command_judge(_COMMAND) is CommandJudge.NOBODY


def _raise(*_args: object, **_kwargs: object) -> Any:
    raise RuntimeError("detector moved")


@pytest.mark.parametrize("mode", ["manual", "smart"])
def test_unread_ignores_allowlist_and_session_grants(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    _install(
        monkeypatch,
        mode=lambda: mode,
        allow=lambda _command: True,
        pending=lambda _findings, _approved: None,
    )
    detection = sys.modules["tools.approval_detection"]
    monkeypatch.setattr(
        detection, "hardline_scan_incomplete", lambda _command: True, raising=False
    )
    assert command_judge(_COMMAND) is CommandJudge.PERSON


@pytest.mark.parametrize(
    "overrides",
    [
        {"mode": lambda: "off"},
        {"yolo": lambda: True},
        {"presence": lambda _cb: (None, False, False, False)},
    ],
)
def test_unread_without_a_reviewer_is_refused(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, Any]
) -> None:
    _install(monkeypatch, **overrides)
    monkeypatch.setattr(
        sys.modules["tools.approval_detection"],
        "hardline_scan_incomplete",
        lambda _command: True,
        raising=False,
    )
    assert command_judge(_COMMAND) is CommandJudge.REFUSED


def test_manual_only_skips_guardian(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, mode=lambda: "smart")
    monkeypatch.setattr(
        sys.modules["tools.approval_detection"],
        "SMART_MANUAL_ONLY_DESCRIPTIONS",
        frozenset({"delete"}),
        raising=False,
    )
    assert command_judge(_COMMAND) is CommandJudge.PERSON


@pytest.mark.parametrize("symbol", ["hardline_scan_incomplete", "SMART_MANUAL_ONLY_DESCRIPTIONS"])
def test_new_missing_or_raising_probes_keep_the_decision_here(
    monkeypatch: pytest.MonkeyPatch, symbol: str
) -> None:
    _install(monkeypatch, mode=lambda: "smart")
    # Missing v0.23.1 names retain the historical guardian route.
    assert command_judge(_COMMAND) is CommandJudge.GUARDIAN
    monkeypatch.setattr(
        sys.modules["tools.approval_detection"],
        symbol,
        _raise if symbol == "hardline_scan_incomplete" else object(),
        raising=False,
    )
    assert command_judge(_COMMAND) is CommandJudge.NOBODY


@pytest.mark.parametrize(
    "description, expected",
    [("hermes config set approval settings", True), ("delete", False), (None, False)],
)
def test_approval_policy_detection_uses_hermes(
    monkeypatch: pytest.MonkeyPatch, description: str | None, expected: bool
) -> None:
    from petasos.hermes.host import approval_policy_command

    _install(monkeypatch, detect=lambda _command: (True, description, description))
    assert approval_policy_command("hermes config set approvals.mode manual") is expected
    _install(monkeypatch, detect=None)
    assert not approval_policy_command("hermes config set approvals.mode manual")


@pytest.mark.parametrize("scope", ["session", "always"])
def test_a_prior_approval_policy_grant_is_not_a_fresh_person(
    monkeypatch: pytest.MonkeyPatch, scope: str
) -> None:
    description = "hermes config set approval settings"
    _install(
        monkeypatch,
        detect=lambda _command: (True, description, description),
        findings=lambda _command: [(description, description)],
        scope=lambda _session, _key: scope,
        pending=lambda findings, approved: (
            None if all(approved(key) for key, _ in findings) else ([description], description)
        ),
    )
    assert command_judge("hermes config set approvals.mode manual") is CommandJudge.NOBODY


def test_a_covered_manual_only_finding_does_not_own_other_pending_findings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        mode=lambda: "smart",
        findings=lambda _command: [("manual", "manual"), ("delete", "delete")],
        scope=lambda _session, key: "session" if key == "manual" else None,
        pending=lambda findings, approved: (
            [key for key, _ in findings if not approved(key)],
            "delete",
        ),
    )
    monkeypatch.setattr(
        sys.modules["tools.approval_detection"],
        "SMART_MANUAL_ONLY_DESCRIPTIONS",
        frozenset({"manual"}),
        raising=False,
    )
    assert command_judge(_COMMAND) is CommandJudge.GUARDIAN
