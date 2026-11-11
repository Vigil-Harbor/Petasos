"""The Hermes predicate, with the host modules stood in.

Each test turns one condition off. The live gate is pinned in
``tests/hermes_host/test_command_will_be_asked.py``.
"""

from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING, Any

from petasos.hermes.host import command_will_be_asked

if TYPE_CHECKING:
    import pytest

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


def test_a_flagged_command_with_a_person_present_is_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch)
    assert command_will_be_asked(_COMMAND) is True


def test_each_host_fact_that_means_nobody_is_asked_answers_no(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases: list[tuple[str, dict[str, Any]]] = [
        ("not flagged", {"detect": lambda _command: (False, None, None)}),
        ("raises", {"detect": _raise}),
        ("missing detector", {"detect": None}),
        ("container", {"skip": lambda _env, has_host_access=False: True}),
        ("hardline", {"floor": lambda _command, sudo_guard=False: {"approved": False}}),
        ("mode off", {"mode": lambda: "off"}),
        ("smart mode", {"mode": lambda: "smart"}),
        ("unknown mode", {"mode": lambda: "approve"}),
        ("yolo", {"yolo": lambda: True}),
        ("allowlist", {"allow": lambda _command: True}),
        ("headless", {"presence": lambda _callback=None: (None, False, False, False)}),
        ("already approved", {"pending": lambda _findings, _approved: None}),
        ("backend moved", {"config": _raise}),
    ]
    for name, overrides in cases:
        _install(monkeypatch, **overrides)
        assert command_will_be_asked(_COMMAND) is False, name


def test_a_missing_hermes_answers_no(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("petasos.hermes.host.load_module", lambda _name: None)
    assert command_will_be_asked(_COMMAND) is False


def _raise(*_args: object, **_kwargs: object) -> Any:
    raise RuntimeError("detector moved")
