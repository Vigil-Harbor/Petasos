"""Order of plugin pre_tool_call and Hermes's own command gate.

Skipped unless ``PETASOS_HERMES_SANDBOX`` names a prepared sandbox. The
dangerous command string is never executed: the harness refuses every
command except ``echo ok``, and denies the command-gate prompt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.hermes_host.client import Sandbox, call
from tests.hermes_host.marks import requires_hermes_sandbox

pytestmark = requires_hermes_sandbox

_HARNESS = Path(__file__).resolve().parent / "order_harness.py"


def _order(box: Sandbox, case: str) -> dict[str, Any]:
    return call(box, {"action": "order", "case": case}, harness=_HARNESS, timeout=120)


def test_terminal_hook_runs_before_the_command_gate(standin: Sandbox) -> None:
    """Pin terminal hook runs before the command gate."""
    result = _order(standin, "terminal_echo")
    assert result["order"] == ["pre_tool_call", "command_gate", "execute", "post_tool_call"]
    assert result["executed"] == ["echo ok"]
    assert '"output": "ok"' in result["result"]


def test_execute_code_hook_runs_before_the_script_gate(standin: Sandbox) -> None:
    """Pin execute code hook runs before the script gate."""
    result = _order(standin, "execute_code_print")
    assert result["order"] == [
        "pre_tool_call",
        "execute_code_gate",
        "kernel_entry",
        "post_tool_call",
    ]
    assert result["executed"] == []


def test_plugin_block_skips_the_terminal_gate(standin: Sandbox) -> None:
    """Pin plugin block skips the terminal gate."""
    result = _order(standin, "terminal_block")
    assert result["order"] == ["pre_tool_call", "post_tool_call"]
    assert result["prompts"] == []
    assert result["executed"] == []
    assert "order-harness-block" in result["result"]


def test_plugin_block_skips_the_execute_code_gate(standin: Sandbox) -> None:
    """Pin plugin block skips the execute code gate."""
    result = _order(standin, "execute_code_block")
    assert result["order"] == ["pre_tool_call", "post_tool_call"]
    assert "kernel_entry" not in result["order"]
    assert result["executed"] == []
    assert "order-harness-block" in result["result"]


def test_plugin_approve_and_the_command_gate_ask_twice(standin: Sandbox) -> None:
    """Pin plugin approve and the command gate ask twice."""
    result = _order(standin, "terminal_twice")
    assert result["order"] == ["pre_tool_call", "command_gate", "post_tool_call"]
    assert len(result["prompts"]) == 2
    assert result["prompts"][0]["command"].startswith("<terminal>")
    assert "rm -rf /tmp/petasos-s2-not-a-real-target" in result["prompts"][1]["command"]
    assert result["executed"] == []
    assert "BLOCKED" in result["result"]


def test_plugin_approve_and_the_script_gate_ask_twice(standin: Sandbox) -> None:
    """Pin plugin approve and the script gate ask twice."""
    result = _order(standin, "execute_code_twice")
    assert result["order"] == ["pre_tool_call", "execute_code_gate", "post_tool_call"]
    assert len(result["prompts"]) == 2
    assert result["prompts"][0]["command"].startswith("<execute_code>")
    assert "execute_code" in result["prompts"][1]["command"]
    assert "kernel_entry" not in result["order"]
    assert result["executed"] == []
    assert "BLOCKED" in result["result"]


def test_write_file_does_not_enter_the_command_gate(standin: Sandbox) -> None:
    """Pin write file does not enter the command gate."""
    result = _order(standin, "write_file")
    assert result["order"][0] == "pre_tool_call"
    assert "command_gate" not in result["order"]
    assert "execute_code_gate" not in result["order"]
    assert result["executed"] == []
    assert "bytes_written" in result["result"]


def test_headless_manual_gate_approves_without_executing(standin: Sandbox) -> None:
    """Pin headless manual gate approves without executing."""
    result = _order(standin, "headless_gate")
    assert result["order"] == ["command_gate", "command_gate"]
    assert result["prompts"] == []
    assert result["executed"] == []
    assert result["dangerous_approved"] is True
    assert result["hardline_approved"] is False


def test_plugin_block_stops_a_command_the_gate_would_auto_approve(standin: Sandbox) -> None:
    """Pin plugin block stops a command the gate would auto approve."""
    result = _order(standin, "mode_off_block")
    assert result["order"] == ["pre_tool_call", "post_tool_call"]
    assert "command_gate" not in result["order"]
    assert result["executed"] == []
    assert "order-harness-block" in result["result"]
