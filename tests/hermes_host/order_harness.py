"""Drive one Hermes tool call and record hook order.

Run this file with the sandbox interpreter, through ``bin/with-sandbox``.
It does not import Hermes at import time. A dangerous command string is
handed to the gate only behind a tripwire that refuses to execute anything
other than ``echo ok``.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

if __name__ == "__main__" and __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.hermes_host.sandbox_guard import sandbox_root

SAFE_COMMAND = "echo ok"
DANGEROUS_COMMAND = "rm -rf /tmp/petasos-s2-not-a-real-target"
ORDER: list[str] = []
PROMPTS: list[dict[str, str]] = []
EXECUTED: list[str] = []


def _note(event: str) -> None:
    ORDER.append(event)


def _callback(command: str, description: str, **_kwargs: Any) -> str:
    PROMPTS.append({"command": command[:200], "description": description[:200]})
    if command.startswith("<"):
        return "once"
    return "deny"


def _load(name: str) -> Any:
    return importlib.import_module(name)


def _install(mode: str) -> None:
    config = _load("hermes_cli.config")
    model_tools = _load("model_tools")
    plugins = _load("hermes_cli.plugins")
    base = _load("tools.environments.base")

    loaded = config.load_config()
    approvals = loaded.get("approvals")
    if not isinstance(approvals, dict):
        approvals = {}
    approvals["mode"] = mode
    loaded["approvals"] = approvals
    config.save_config(loaded)

    real_pre = plugins._dispatch_pre_tool_call_hooks
    real_post = model_tools._emit_post_tool_call_hook
    real_execute = base.BaseEnvironment.execute

    def pre(*args: Any, **kwargs: Any) -> Any:
        _note("pre_tool_call")
        return real_pre(*args, **kwargs)

    def post(*args: Any, **kwargs: Any) -> Any:
        _note("post_tool_call")
        return real_post(*args, **kwargs)

    def execute(self: Any, command: str, *args: Any, **kwargs: Any) -> Any:
        text = command if isinstance(command, str) else ""
        EXECUTED.append(text)
        _note("execute")
        if text.strip() != SAFE_COMMAND:
            raise RuntimeError("tripwire refused to execute")
        return real_execute(self, command, *args, **kwargs)

    plugins._dispatch_pre_tool_call_hooks = pre
    model_tools._emit_post_tool_call_hook = post
    base.BaseEnvironment.execute = execute

    approval = _load("tools.approval")
    code_kernel = _load("tools.code_kernel")
    terminal = _load("tools.terminal_tool")
    real_command = approval.check_all_command_guards
    real_script = approval.check_execute_code_guard

    def command_gate(*args: Any, **kwargs: Any) -> Any:
        _note("command_gate")
        return real_command(*args, **kwargs)

    def script_gate(*args: Any, **kwargs: Any) -> Any:
        _note("execute_code_gate")
        return real_script(*args, **kwargs)

    def kernel(*_args: Any, **_kwargs: Any) -> str:
        _note("kernel_entry")
        raise RuntimeError("tripwire refused to spawn an execute_code kernel")

    approval.check_all_command_guards = command_gate
    approval.check_execute_code_guard = script_gate
    terminal._check_all_guards_impl = command_gate
    terminal.set_approval_callback(_callback)
    code_kernel.execute_in_session_kernel = kernel


def _behavior(action: str | None) -> None:
    host: dict[str, Any] = {}
    if action == "block":
        host = {"return": {"action": "block", "message": "order-harness-block"}}
    elif action == "approve":
        host = {
            "return": {
                "action": "approve",
                "message": "plugin wants a person",
                "rule_key": "order",
            },
        }
    os.environ["STANDIN_BEHAVIOR"] = json.dumps(
        {
            "standin-hostfacts": {"pre_tool_call": host},
            "standin-b": {"pre_tool_call": {}},
        }
    )
    os.environ["STANDIN_LOG"] = str(Path(os.environ.get("TMPDIR", "/tmp")) / "order-harness.jsonl")


def _dispatch(tool: str, args: dict[str, Any]) -> str:
    model_tools = _load("model_tools")
    result = model_tools.handle_function_call(
        tool,
        args,
        task_id="order-task",
        session_id="order-session",
        tool_call_id="order-call",
        turn_id="order-turn",
    )
    return result if isinstance(result, str) else json.dumps(result)


def order_case(request: dict[str, Any]) -> dict[str, Any]:
    """Run one named case and return the event order."""
    sandbox_root()
    case = str(request["case"])
    mode = "off" if case == "mode_off_block" else "manual"
    _install(mode)
    if case == "terminal_echo":
        _behavior(None)
        result = _dispatch("terminal", {"command": SAFE_COMMAND})
    elif case == "execute_code_print":
        _behavior(None)
        result = _dispatch("execute_code", {"code": 'print("ok")'})
    elif case == "terminal_block":
        _behavior("block")
        os.environ["HERMES_INTERACTIVE"] = "1"
        result = _dispatch("terminal", {"command": DANGEROUS_COMMAND})
    elif case == "execute_code_block":
        _behavior("block")
        result = _dispatch("execute_code", {"code": 'print("ok")'})
    elif case == "terminal_twice":
        _behavior("approve")
        os.environ["HERMES_INTERACTIVE"] = "1"
        result = _dispatch("terminal", {"command": DANGEROUS_COMMAND})
    elif case == "execute_code_twice":
        _behavior("approve")
        os.environ["HERMES_INTERACTIVE"] = "1"
        os.environ["HERMES_EXEC_ASK"] = "1"
        result = _dispatch("execute_code", {"code": 'print("ok")'})
    elif case == "write_file":
        _behavior(None)
        path = str(Path(os.environ.get("TMPDIR", "/tmp")) / f"order-note-{uuid.uuid4().hex}.txt")
        result = _dispatch("write_file", {"path": path, "content": "ok"})
    elif case == "mode_off_block":
        _behavior("block")
        result = _dispatch("terminal", {"command": SAFE_COMMAND})
    elif case == "headless_gate":
        _behavior(None)
        approval = _load("tools.approval")
        dangerous = approval.check_all_command_guards(DANGEROUS_COMMAND, "local")
        hardline = approval.check_all_command_guards("rm -rf /", "local")
        return {
            "case": case,
            "order": list(ORDER),
            "prompts": list(PROMPTS),
            "executed": list(EXECUTED),
            "result": "",
            "dangerous_approved": bool(dangerous.get("approved")),
            "hardline_approved": bool(hardline.get("approved")),
        }
    else:
        raise SystemExit(f"unknown case {case}")
    return {
        "case": case,
        "order": list(ORDER),
        "prompts": list(PROMPTS),
        "executed": list(EXECUTED),
        "result": result[:400],
    }


def main() -> None:
    """Run the isolated test harness."""
    request = json.load(sys.stdin)
    if request.get("action") != "order":
        raise SystemExit(f"unknown action {request.get('action')}")
    json.dump(order_case(request), sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
