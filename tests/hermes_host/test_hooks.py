"""Question 4: hook decisions from Hermes's real dispatchers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tests.hermes_host.client import invoke
from tests.hermes_host.marks import requires_hermes_sandbox

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = requires_hermes_sandbox

PRE_KEYS = {
    "tool_name",
    "args",
    "task_id",
    "session_id",
    "tool_call_id",
    "turn_id",
    "api_request_id",
    "conversation_id",
    "middleware_trace",
    "telemetry_schema_version",
}


def _pre(sandbox: Path, behavior: dict[str, Any], **extra: Any) -> dict[str, Any]:
    request: dict[str, Any] = {"action": "dispatch", "hook": "pre_tool_call", "behavior": behavior}
    request.update(extra)
    return invoke(sandbox, request)


def test_pre_tool_call_block_none_and_unknown(hermes_sandbox: Path) -> None:
    blocked = _pre(hermes_sandbox, {"return": {"action": "block", "message": "stopped"}})
    assert blocked["host"]["block"] == "stopped"
    assert set(blocked["keys"]) >= PRE_KEYS

    empty = _pre(hermes_sandbox, {"return": {"action": "block"}}, tool_call_id="call-empty")
    assert empty["host"]["block"] is None

    nothing = _pre(hermes_sandbox, {"return": None}, tool_call_id="call-none")
    assert nothing["host"]["block"] is None

    unknown = _pre(
        hermes_sandbox,
        {"return": {"action": "dance", "message": "nope"}},
        tool_call_id="call-unknown",
    )
    assert unknown["host"]["block"] is None


def test_pre_tool_call_raise_and_timeout(hermes_sandbox: Path) -> None:
    raised = _pre(hermes_sandbox, {"raise": "boom"}, tool_call_id="call-raise")
    message = raised["host"]["block"]
    assert isinstance(message, str)
    assert "RuntimeError" in message
    assert "on_pre_tool_call" in message

    timed = invoke(hermes_sandbox, {"action": "timeout_probe"}, timeout=60)
    assert timed["decision"]["host"]["block"] == (
        "pre_tool_call plugin callback timed out or is still running"
    )
    assert timed["elapsed_s"] < 15


def test_transform_tool_result(hermes_sandbox: Path) -> None:
    replaced = invoke(
        hermes_sandbox,
        {
            "action": "dispatch",
            "hook": "transform_tool_result",
            "behaviors": {
                "standin-hostfacts": {"transform_tool_result": {"return": "from-a"}},
                "standin-b": {"transform_tool_result": {"return": None}},
            },
        },
    )
    assert replaced["host"]["result"] == "from-a"
    assert "result" in replaced["keys"]

    kept = invoke(
        hermes_sandbox,
        {
            "action": "dispatch",
            "hook": "transform_tool_result",
            "behavior": {"return": None},
        },
    )
    assert kept["host"]["result"] == "original-result"

    failed = invoke(
        hermes_sandbox,
        {
            "action": "dispatch",
            "hook": "transform_tool_result",
            "behavior": {"raise": "transform-boom"},
        },
    )
    assert failed["host"]["result"] == "original-result"

    both = invoke(
        hermes_sandbox,
        {
            "action": "dispatch",
            "hook": "transform_tool_result",
            "behaviors": {
                "standin-hostfacts": {"transform_tool_result": {"return": "from-a"}},
                "standin-b": {"transform_tool_result": {"return": "from-b"}},
            },
        },
    )
    # Alphabetical registration: standin-b runs first, and the first string wins.
    assert both["host"]["result"] == "from-b"
