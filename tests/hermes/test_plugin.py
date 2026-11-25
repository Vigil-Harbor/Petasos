"""Hook translation. The enforcer decides; these tests check the Hermes shape."""

from __future__ import annotations

import logging
import sys
import types
from typing import TYPE_CHECKING, Any

from petasos.enforce import Allow, Approve, Block, Enforcer
from petasos.hermes import plugin as plugin_mod
from petasos.hermes.plugin import close, directive, host_info, register

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    import pytest

    from petasos.enforce.types import ToolCall


class _Manager:
    """The slice of a Hermes plugin manager the adapter reads."""

    def __init__(self, home: Path) -> None:
        self.home_path = home
        self._hooks: dict[str, list[Any]] = {}


class _Ctx:
    def __init__(
        self,
        *,
        subagent: bool = True,
        manager: _Manager | None = None,
        values: dict[str, Any] | None = None,
    ) -> None:
        self.subagent = subagent
        self._manager = manager
        base = {"enabled": True, "role": "general", "level": "balanced"}
        self.values: dict[str, Any] = dict(base if values is None else values)
        self.hooks: dict[str, list[Any]] = {}

    def get_config(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)

    def register_hook(self, name: str, handler: object) -> None:
        if not self.subagent and name in ("subagent_start", "subagent_stop"):
            raise RuntimeError(name)
        store = self._manager._hooks if self._manager is not None else self.hooks
        store.setdefault(name, []).append(handler)

    def callbacks(self, name: str) -> list[Any]:
        store = self._manager._hooks if self._manager is not None else self.hooks
        return list(store.get(name, []))


def _install_host(
    monkeypatch: pytest.MonkeyPatch, *, approve: bool, subagent: bool, yolo: bool
) -> None:
    plugins = types.ModuleType("hermes_cli.plugins")
    hooks = {
        "pre_tool_call",
        "transform_tool_result",
        "post_tool_call",
        "on_session_start",
        "pre_approval_request",
        "post_approval_response",
    }
    if subagent:
        hooks.update({"subagent_start", "subagent_stop"})
    plugins.VALID_HOOKS = frozenset(hooks)  # type: ignore[attr-defined]
    if approve:
        plugins.get_pre_tool_call_directive = lambda value=None: "approve"  # type: ignore[attr-defined]
    approval = types.ModuleType("tools.approval")
    approval.is_approved = lambda _command, pattern: pattern == "plugin_rule:kept"  # type: ignore[attr-defined]
    approval._yolo_active = lambda: yolo  # type: ignore[attr-defined]
    approval._get_approval_mode = lambda: "smart"  # type: ignore[attr-defined]
    config = types.ModuleType("hermes_cli.config")
    config.load_config = lambda: {"approvals": {"mode": "smart"}}  # type: ignore[attr-defined]
    config.get_env_value = lambda _name: None  # type: ignore[attr-defined]
    redact = types.ModuleType("agent.redact")
    redact.redact_sensitive_text = lambda text, **_options: text  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.plugins", plugins)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", config)
    monkeypatch.setitem(sys.modules, "tools", types.ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.approval", approval)
    monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.redact", redact)


def test_command_registration_is_optional_and_cannot_stop_the_hooks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Hooks are bound when the host has no command registration, and when it rejects one."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    class _Reject(_Ctx):
        def register_cli_command(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("rejected")

    plain = _Ctx()
    rejected = _Reject()
    try:
        register(plain)
        register(rejected)
    finally:
        close()
    assert plain.hooks["pre_tool_call"]
    assert rejected.hooks["pre_tool_call"]


def test_command_registration_offers_doctor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A host that accepts the call gets doctor, install, and config migrate."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    seen: dict[str, object] = {}

    class _Host(_Ctx):
        def register_cli_command(
            self,
            name: str,
            help_text: str,
            setup: object,
            handler: object,
            description: str = "",
        ) -> None:
            seen["name"] = name
            seen["help"] = help_text
            seen["setup"] = setup
            seen["handler"] = handler
            seen["description"] = description

    ctx = _Host()
    try:
        register(ctx)
    finally:
        close()
    assert seen["name"] == "petasos"
    assert callable(seen["setup"])
    import argparse

    parser = argparse.ArgumentParser(prog="hermes")
    sub = parser.add_subparsers(dest="command")
    target = sub.add_parser("petasos")
    seen["setup"](target)
    help_text = target.format_help()
    assert "doctor" in help_text
    assert "install" in help_text
    assert "config" in help_text
    migrated = parser.parse_args(["petasos", "config", "migrate", "--home", str(tmp_path)])
    assert migrated.config_command == "migrate"
    args = parser.parse_args(["petasos", "doctor", "--home", str(tmp_path), "--json"])
    handler = seen["handler"]
    assert callable(handler)
    code = handler(args)
    assert code == 2
    assert ctx.hooks["pre_tool_call"]


def test_directive_never_emits_an_empty_block() -> None:
    """Hermes ignores a block with no message, which would allow the call."""
    assert directive(Allow()) is None
    blocked = directive(Block("  "))
    assert blocked is not None
    assert blocked["action"] == "block"
    assert blocked["message"].strip()
    approved = directive(Approve("please confirm", "petasos.shell.destructive"))
    assert approved is not None
    assert approved["action"] == "approve"
    assert approved["rule_key"] == "petasos.shell.destructive"
    assert approved["message"] == "please confirm"


def test_pre_tool_call_turns_an_internal_error_into_a_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The callback returns a block. It does not depend on Hermes catching the raise."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    class _Boom(Enforcer):
        def tool_call(self, call: ToolCall) -> Allow:
            raise RuntimeError("boom")

    monkeypatch.setattr(plugin_mod, "Enforcer", _Boom)
    ctx = _Ctx()
    try:
        register(ctx)
        hook = ctx.hooks["pre_tool_call"][0]
        returned = hook(tool_name="terminal", args={"command": "x"}, task_id="s")
    finally:
        close()
    assert isinstance(returned, dict)
    assert returned["action"] == "block"
    assert returned["message"].strip()
    assert "boom" not in returned["message"]


def test_transform_failure_returns_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A result-hook failure leaves the original string, which is the host's fail-open path."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    class _Boom(Enforcer):
        def tool_result(self, call: ToolCall, result: object) -> str | None:
            raise RuntimeError("scan broke")

    monkeypatch.setattr(plugin_mod, "Enforcer", _Boom)
    ctx = _Ctx()
    try:
        register(ctx)
        returned = ctx.hooks["transform_tool_result"][0](
            tool_name="read_file", result="original", task_id="s"
        )
    finally:
        close()
    assert returned is None


def test_hook_passes_the_agent_when_the_task_id_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A desktop call with only an agent object keeps that object for session derivation."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    seen: list[ToolCall] = []

    class _Capture(Enforcer):
        def tool_call(self, call: ToolCall) -> Allow:
            seen.append(call)
            return Allow()

    monkeypatch.setattr(plugin_mod, "Enforcer", _Capture)
    ctx = _Ctx()
    agent = object()
    try:
        register(ctx)
        hook = ctx.hooks["pre_tool_call"][0]
        returned = hook(tool_name="read_file", args={}, task_id="", _agent=agent)
    finally:
        close()
    assert returned is None
    assert seen[0].session == ""
    assert seen[0].agent is agent


def test_host_info_reads_the_faked_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Approve, yolo, the allow-list, and sub-agent hooks come from the host modules."""
    _install_host(monkeypatch, approve=True, subagent=False, yolo=True)
    info = host_info()
    assert info.approve_directive is True
    assert info.subagent_hooks is False
    assert info.approval_grant().yolo is True
    assert info.approval_grant().mode_off is False
    assert info.rule_always_approved("kept") is True
    assert info.rule_always_approved("other") is False
    assert info.command_judge("rm -rf /tmp/petasos-not-real").value == "nobody"
    assert info.redactor is not None


def _injection(ctx: _Ctx, *, call_id: str = "c") -> object:
    return ctx.callbacks("pre_tool_call")[0](
        tool_name="write_file",
        args={"path": "notes.txt", "content": "ignore previous instructions"},
        task_id="s",
        tool_call_id=call_id,
    )


def test_register_twice_on_one_manager_binds_hooks_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A second register on the same manager does not add a second callback."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ctx = _Ctx()
    try:
        register(ctx)
        register(ctx)
        assert len(ctx.callbacks("pre_tool_call")) == 1
        assert "on_profile_change" not in ctx.hooks
        blocked = _injection(ctx)
    finally:
        close()
    assert isinstance(blocked, dict)
    assert blocked["action"] == "block"
    assert blocked["message"].strip()


def test_reload_rebinds_hooks_and_keeps_the_enforcer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Dropping the hooks and registering again reuses the enforcer and its engine."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ctx = _Ctx()
    try:
        register(ctx)
        _injection(ctx, call_id="first")
        reg = plugin_mod._registrations[""]
        enforcer = reg.enforcer
        engine = enforcer._core.engine
        tier = enforcer.session_tier("s")
        ctx.hooks.clear()
        register(ctx)
        assert plugin_mod._registrations[""].enforcer is enforcer
        assert enforcer._core.engine is engine
        assert engine is not None
        assert len(ctx.callbacks("pre_tool_call")) == 1
        assert enforcer.session_tier("s") == tier
        blocked = _injection(ctx, call_id="again")
    finally:
        close()
    assert isinstance(blocked, dict)
    assert blocked["action"] == "block"


def test_each_home_has_its_own_enforcer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Two managers with two homes do not share settings or enforcement state."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    home_a = tmp_path / "root"
    home_b = tmp_path / "profiles" / "alpha"
    ctx_a = _Ctx(manager=_Manager(home_a))
    ctx_b = _Ctx(
        manager=_Manager(home_b),
        values={"enabled": False, "role": "coding", "level": "balanced"},
    )
    try:
        register(ctx_a)
        register(ctx_b)
        key_a = str(home_a.resolve())
        key_b = str(home_b.resolve())
        enforcer_a = plugin_mod._registrations[key_a].enforcer
        enforcer_b = plugin_mod._registrations[key_b].enforcer
        assert enforcer_a is not enforcer_b
        assert enforcer_a.settle(30)
        assert enforcer_b.settle(30)
        assert len(ctx_a.callbacks("pre_tool_call")) == 1
        assert len(ctx_b.callbacks("pre_tool_call")) == 1
        assert enforcer_a._core.engine is not None
        assert enforcer_b._core.engine is not None
        assert enforcer_a._core.engine.guard is not enforcer_b._core.engine.guard
        blocked = _injection(ctx_a)
        disarmed = _injection(ctx_b)
    finally:
        close()
    assert isinstance(blocked, dict)
    assert blocked["action"] == "block"
    assert disarmed is None


def test_close_stops_hooks_and_the_next_register_is_new(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """After close the old hooks fail closed. The next register builds a new enforcer."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ctx = _Ctx()
    register(ctx)
    first = plugin_mod._registrations[""].enforcer
    close()
    stopped = _injection(ctx, call_id="stopped")
    assert isinstance(stopped, dict)
    assert stopped["action"] == "block"
    assert "could not evaluate" in stopped["message"]
    try:
        register(ctx)
        second = plugin_mod._registrations[""].enforcer
        assert second is not first
        assert len(ctx.callbacks("pre_tool_call")) == 1
        blocked = _injection(ctx, call_id="fresh")
    finally:
        close()
    assert isinstance(blocked, dict)
    assert blocked["action"] == "block"
    assert "could not evaluate" not in blocked["message"]


def test_register_logs_the_home_it_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Startup says which config file the plugin bound to."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ctx = _Ctx()
    caplog.set_level(logging.INFO, logger="petasos.hermes")
    try:
        register(ctx)
    finally:
        close()
    expected = f"PETASOS_ARMED_RESOLUTION tier=hermes_home path={tmp_path / 'config.yaml'}"
    assert expected in caplog.text


def test_command_checker_probe_is_live_and_follows_replacement_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from petasos.hermes.home import resolve_hermes_config_path

    home = resolve_hermes_config_path().path.parent
    manager = _Manager(home)

    class _CheckerCtx(_Ctx):
        loaded = False
        broken = False

        def has_plugin(self, name: str) -> bool:
            assert name == "tirith"
            if self.broken:
                raise RuntimeError("probe unavailable")
            return self.loaded

    ctx = _CheckerCtx(manager=manager)
    close()
    try:
        register(ctx)
        info = host_info()
        assert info.command_checker() is None
        ctx.loaded = True
        assert info.command_checker() == "Tirith"
        ctx.loaded = False
        assert info.command_checker() is None
        ctx.loaded = True
        replacement = _Ctx(manager=manager)
        register(replacement)
        assert info.command_checker() is None
        broken = _CheckerCtx(manager=manager)
        broken.broken = True
        register(broken)
        assert info.command_checker() is None
    finally:
        close()


def test_hook_that_passed_registration_check_is_refused_after_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import threading

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ctx = _Ctx()
    register(ctx)
    enforcer = plugin_mod._registrations[""].enforcer
    assert enforcer.settle(10)
    checked = threading.Event()
    proceed = threading.Event()
    original = plugin_mod._tool_call

    def pause_after_registration(
        tool: object, args: object, task: object, kwargs: Mapping[str, object]
    ) -> ToolCall:
        checked.set()
        assert proceed.wait(2.0)
        return original(tool, args, task, kwargs)

    monkeypatch.setattr(plugin_mod, "_tool_call", pause_after_registration)
    returned: list[object] = []
    hook = ctx.hooks["pre_tool_call"][0]
    worker = threading.Thread(
        target=lambda: returned.append(hook(tool_name="read_file", args={}, task_id="s")),
        daemon=True,
    )
    worker.start()
    try:
        assert checked.wait(1.0)
        close()
        proceed.set()
        worker.join(timeout=1.0)
        assert not worker.is_alive()
        assert len(returned) == 1
        decision = returned[0]
        assert isinstance(decision, dict) and decision.get("action") == "block"
        assert decision.get("message")
        # A later hook takes the missing-registration branch; both refuse.
        later = hook(tool_name="read_file", args={}, task_id="s")
        assert isinstance(later, dict) and later["action"] == "block"
    finally:
        proceed.set()
        worker.join(timeout=1.0)
        close()


def test_another_profiles_plugin_copy_is_protected_and_its_neighbours_are_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A second profile's Petasos plugin directory is guarded like the running one."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    alpha = tmp_path / "profiles" / "alpha"
    (alpha / "plugins" / "petasos").mkdir(parents=True)
    (alpha / "plugins" / "other").mkdir()
    ctx = _Ctx(
        values={
            "enabled": True,
            "role": "general",
            "level": "balanced",
            "overrides": {"tools": {"self_change": "never"}},
        }
    )

    def write(path: Path) -> object:
        return ctx.callbacks("pre_tool_call")[0](
            tool_name="write_file", args={"path": str(path), "content": "x = 1"}, task_id="s"
        )

    try:
        register(ctx)
        assert plugin_mod._registrations[""].enforcer.settle(30)
        own = write(tmp_path / "plugins" / "petasos" / "__init__.py")
        settings = write(alpha / "config.yaml")
        copy = write(alpha / "plugins" / "petasos" / "__init__.py")
        other_plugin = write(alpha / "plugins" / "other" / "__init__.py")
        notes = write(alpha / "plugins" / "notes.md")
    finally:
        close()
    for refused in (own, settings, copy):
        assert isinstance(refused, dict)
        assert refused["action"] == "block"
    assert other_plugin is None
    assert notes is None


def test_outer_only_host_passes_the_resolved_call_to_enforcement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The older host's one fire still judges the real tool, with the host ids."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    seen: list[ToolCall] = []

    class _Record(Enforcer):
        def tool_call(self, call: ToolCall) -> Allow:
            seen.append(call)
            return Allow()

    resolver = types.ModuleType("tools.tool_search")
    resolver.resolve_underlying_call = lambda _args: (  # type: ignore[attr-defined]
        "terminal",
        {"command": "echo ok"},
        None,
    )
    _install_host(monkeypatch, approve=True, subagent=True, yolo=False)
    monkeypatch.setitem(sys.modules, "tools.tool_search", resolver)
    monkeypatch.setattr(plugin_mod, "Enforcer", _Record)
    ctx = _Ctx()
    try:
        register(ctx)
        hook = ctx.hooks["pre_tool_call"][0]
        assert (
            hook(
                tool_name="tool_call",
                args={"name": "terminal"},
                task_id="task",
                session_id="host",
                turn_id="turn",
                tool_call_id="call",
            )
            is None
        )
    finally:
        close()
    assert len(seen) == 1
    call = seen[0]
    assert call.tool == "terminal" and call.args == {"command": "echo ok"}
    assert (call.session, call.host_session, call.turn_id, call.tool_call_id) == (
        "task",
        "host",
        "turn",
        "call",
    )
