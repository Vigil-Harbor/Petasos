"""Guardrail changes through Hermes's own hook dispatch. No gateway and no model."""

from __future__ import annotations

import json
import subprocess

from tests.hermes_host.client import Sandbox, sandbox_env
from tests.hermes_host.marks import requires_hermes_sandbox

pytestmark = requires_hermes_sandbox

_SNIPPET = r"""
import json
from pathlib import Path

home = Path(__import__("os").environ["HERMES_HOME"])
config = home / "config.yaml"
plugin = home / "plugins" / "petasos"

from hermes_cli.plugins import (
    _dispatch_pre_tool_call_hooks,
    _get_pre_tool_call_directive_details,
    get_plugin_manager,
)
from hermes_cli.plugins_settings import save_plugin_settings

manager = get_plugin_manager()
manager.discover_and_load()


def save(mode):
    overrides = {"tools": {"self_change": mode}}
    save_plugin_settings(
        "petasos",
        plugin,
        {"enabled": True, "role": "general", "level": "balanced", "overrides": overrides},
    )


def dispatch(tool, args, call, session):
    block, _modified = _dispatch_pre_tool_call_hooks(
        tool,
        args,
        task_id=session,
        session_id=session,
        tool_call_id=call,
        turn_id="turn-1",
    )
    return block


def directive(tool, args, call, session):
    details = _get_pre_tool_call_directive_details(
        tool,
        args,
        task_id=session,
        session_id=session,
        tool_call_id=call,
        turn_id="turn-1",
    )
    return {"action": details.action, "rule_key": details.rule_key, "message": details.message}


def enabled():
    text = config.read_text(encoding="utf-8")
    return "petasos" in text


save("never")
before = config.read_text(encoding="utf-8")
write_block = dispatch(
    "write_file",
    {"path": str(config), "content": "enabled: false\n"},
    "write-never",
    "never-write",
)
after_write = config.read_text(encoding="utf-8")
disable_block = dispatch(
    "terminal",
    {"command": "hermes plugins disable petasos"},
    "disable-never",
    "never-disable",
)
save("approve")
open_before = config.read_text(encoding="utf-8")
unattended_write = dispatch(
    "write_file",
    {"path": str(config), "content": "enabled: false\n"},
    "write-open",
    "open-write",
)
after_unattended = config.read_text(encoding="utf-8")
unattended_disable = dispatch(
    "terminal",
    {"command": "hermes plugins disable petasos"},
    "disable-open",
    "open-disable",
)
asked = directive(
    "write_file",
    {"path": str(config), "content": "enabled: false\n"},
    "write-ask",
    "ask-session",
)
print(json.dumps({
    "write_block": write_block,
    "write_unchanged": after_write == before,
    "disable_block": disable_block,
    "still_enabled": enabled(),
    "unattended_write": unattended_write,
    "unattended_unchanged": after_unattended == open_before,
    "unattended_disable": unattended_disable,
    "still_enabled_after": enabled(),
    "asked": asked,
}))
"""


def _run(box: Sandbox) -> dict[str, object]:
    completed = subprocess.run(
        [
            str(box.root / "bin" / "with-sandbox"),
            str(box.root / "venv" / "bin" / "python"),
            "-c",
            _SNIPPET,
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        env=sandbox_env(box.home),
    )
    if completed.returncode != 0:
        raise AssertionError(f"snippet exited {completed.returncode}\n{completed.stderr[-2000:]}")
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise AssertionError("snippet did not return an object")
    return payload


def test_hermes_dispatch_blocks_or_asks_with_a_session_key(installed: Sandbox) -> None:
    """Never and unattended approve block. A directive Hermes can ask carries the session key."""
    result = _run(installed)
    write_block = result["write_block"]
    disable_block = result["disable_block"]
    assert isinstance(write_block, str) and "refused" in write_block
    assert "outside the agent" in write_block
    assert result["write_unchanged"] is True
    assert isinstance(disable_block, str) and disable_block.strip()
    assert result["still_enabled"] is True

    unattended_write = result["unattended_write"]
    unattended_disable = result["unattended_disable"]
    assert isinstance(unattended_write, str)
    assert "no interactive user or gateway is present" in unattended_write
    assert result["unattended_unchanged"] is True
    assert isinstance(unattended_disable, str) and unattended_disable.strip()
    assert result["still_enabled_after"] is True

    asked = result["asked"]
    assert isinstance(asked, dict)
    assert asked["action"] == "approve"
    rule_key = asked["rule_key"]
    assert isinstance(rule_key, str)
    assert rule_key.startswith("petasos.guardrail.")
    assert rule_key.endswith(".ask-session")
