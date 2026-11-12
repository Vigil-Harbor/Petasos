"""Guardrail changes through Hermes's own hook dispatch. No gateway and no model."""

from __future__ import annotations

import json
import subprocess

from tests.hermes_host.client import Sandbox, sandbox_env
from tests.hermes_host.marks import requires_hermes_sandbox

pytestmark = requires_hermes_sandbox

_HEADER = r"""
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

get_plugin_manager().discover_and_load()


def save(mode):
    save_plugin_settings(
        "petasos",
        plugin,
        {
            "enabled": True,
            "role": "general",
            "level": "balanced",
            "overrides": {"tools": {"self_change": mode}},
        },
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
    return {"action": details.action, "rule_key": details.rule_key}


def enabled():
    return "petasos" in config.read_text(encoding="utf-8")
"""

_WRITE = '{"path": str(config), "content": "enabled: false\\n"}'


def _run(box: Sandbox, body: str) -> dict[str, object]:
    completed = subprocess.run(
        [
            str(box.root / "bin" / "with-sandbox"),
            str(box.root / "venv" / "bin" / "python"),
            "-c",
            _HEADER + "\n" + body,
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


def _blocked(result: dict[str, object]) -> str:
    block = result["block"]
    assert isinstance(block, str) and block.strip()
    return block


def test_under_never_a_write_of_the_profile_config_is_blocked(installed: Sandbox) -> None:
    """A tool call that writes the profile config is refused, and the file stays as it was."""
    result = _run(
        installed,
        f"""
save("never")
before = config.read_text(encoding="utf-8")
block = dispatch("write_file", {_WRITE}, "write-never", "never-write")
after = config.read_text(encoding="utf-8")
print(json.dumps({{"block": block, "unchanged": after == before}}))
""",
    )
    block = _blocked(result)
    assert "refused" in block
    assert "outside the agent" in block
    assert result["unchanged"] is True


def test_under_never_disabling_petasos_is_blocked(installed: Sandbox) -> None:
    """A shell call that disables Petasos is refused, and the plugin stays enabled."""
    result = _run(
        installed,
        """
save("never")
block = dispatch(
    "terminal",
    {"command": "hermes plugins disable petasos"},
    "disable-never",
    "never-disable",
)
print(json.dumps({"block": block, "enabled": enabled()}))
""",
    )
    assert _blocked(result)
    assert result["enabled"] is True


def test_under_approve_with_nobody_to_ask_both_are_blocked(installed: Sandbox) -> None:
    """Approve, with no person attached, still blocks the write and the disable."""
    result = _run(
        installed,
        f"""
save("approve")
before = config.read_text(encoding="utf-8")
write_block = dispatch("write_file", {_WRITE}, "write-open", "open-write")
after = config.read_text(encoding="utf-8")
disable_block = dispatch(
    "terminal",
    {{"command": "hermes plugins disable petasos"}},
    "disable-open",
    "open-disable",
)
print(json.dumps({{
    "write_block": write_block,
    "unchanged": after == before,
    "disable_block": disable_block,
    "enabled": enabled(),
}}))
""",
    )
    write_block = result["write_block"]
    disable_block = result["disable_block"]
    assert isinstance(write_block, str)
    assert "no interactive user or gateway is present" in write_block
    assert result["unchanged"] is True
    assert isinstance(disable_block, str) and disable_block.strip()
    assert result["enabled"] is True


def test_under_approve_hermes_receives_a_directive_carrying_the_session(
    installed: Sandbox,
) -> None:
    """Where Hermes can ask, the approve directive's key carries the session."""
    result = _run(
        installed,
        f"""
save("approve")
asked = directive("write_file", {_WRITE}, "write-ask", "ask-session")
print(json.dumps({{"asked": asked}}))
""",
    )
    asked = result["asked"]
    assert isinstance(asked, dict)
    assert asked["action"] == "approve"
    rule_key = asked["rule_key"]
    assert isinstance(rule_key, str)
    assert rule_key.startswith("petasos.guardrail.")
    assert rule_key.endswith(".ask-session")


def test_under_never_a_code_tool_that_writes_the_config_is_blocked(installed: Sandbox) -> None:
    """Code that opens the profile config for writing is refused, and the file stays."""
    result = _run(
        installed,
        r"""
save("never")
before = config.read_text(encoding="utf-8")
script = "open(" + repr(str(config)) + ", 'w').write('x')\n"
block = dispatch("execute_code", {"code": script}, "code-never", "never-code")
after = config.read_text(encoding="utf-8")
print(json.dumps({"block": block, "unchanged": after == before}))
""",
    )
    block = _blocked(result)
    assert "refused" in block
    assert "outside the agent" in block
    assert result["unchanged"] is True


def test_the_doctor_and_the_overview_agree_under_approve_and_never(installed: Sandbox) -> None:
    """Both modes say open or blocked, and neither offers pinning.

    The agent sentence is the Overview row "The agent" under "Who can change
    these settings". It is taken from the doctor's guardrail line.
    """
    result = _run(
        installed,
        r"""
from petasos.hermes.dashboard.scope import load_home
from petasos.hermes.dashboard.status import status
from petasos.hermes.doctor import examine, render_text


def look(mode):
    save(mode)
    report = examine(home, home_reason="sandbox check", probe_plugin=False)
    line = next(check for check in report.checks if check.id == "guardrail")
    body = status(load_home(home))
    return {
        "summary": line.summary,
        "meaning": line.meaning or "",
        "text": render_text(report, verbose=False, color=False),
        "agent": body["who_can_change"]["agent"],
    }


print(json.dumps({"never": look("never"), "approve": look("approve")}))
""",
    )
    _words(result["never"], "Blocked.")
    approve = _words(result["approve"], "Open.")
    assert isinstance(approve["agent"], str)
    assert "fresh approval" in approve["agent"]


def _words(raw: object, lead: str) -> dict[str, object]:
    assert isinstance(raw, dict)
    summary = raw["summary"]
    meaning = raw["meaning"]
    text = raw["text"]
    agent = raw["agent"]
    assert isinstance(summary, str) and summary.startswith(lead)
    assert isinstance(meaning, str)
    assert isinstance(text, str) and summary in text
    assert isinstance(agent, str) and agent.startswith(summary)
    folded = f"{summary}\n{meaning}\n{agent}".casefold()
    for word in ("pinned", "pinning", "unpin"):
        assert word not in folded
    return raw
