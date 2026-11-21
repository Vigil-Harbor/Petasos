"""Loaded-plugin facts and note composition with a harmless Tirith stand-in."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.hermes_host.client import Sandbox, call
from tests.hermes_host.marks import requires_hermes_sandbox

pytestmark = requires_hermes_sandbox
_HARNESS = Path(__file__).with_name("tirith_harness.py")


@pytest.fixture
def facts(installed: Sandbox) -> dict[str, Any]:
    return call(installed, {"action": "tirith"}, harness=_HARNESS)


def test_loaded_tirith_owns_fetch_execution_and_doctor_explains(facts: dict[str, Any]) -> None:
    assert facts["checker"] == "Tirith"
    assert facts["loaded"] == ["a-output", "petasos", "tirith"]
    events = facts["deferred_events"]
    assert len(events) == 1
    assert events[0]["deferred_to"] == "Tirith"
    assert events[0]["rule_id"] == "petasos.syntactic.command.fetch-exec"
    assert any(row["hook"] == "pre" and "curl" in row["command"] for row in facts["pre_seen"])
    assert "denied" in facts["deferred_result"].lower()
    assert facts["executed"] == ["echo ok", "echo ok"]
    assert len(facts["doctor"]) == 1
    assert "blocking role" in facts["doctor"][0]


def test_first_result_string_wins_but_early_output_note_can_survive(facts: dict[str, Any]) -> None:
    assert facts["both"].startswith("[Petasos]")
    assert "[stand-in Tirith warning]" not in facts["both"]
    assert "[early output note]" in facts["both"]
    assert not facts["clean"].startswith("[Petasos]")
    assert "[stand-in Tirith warning]" in facts["clean"]
    assert "[early output note]" in facts["clean"]
    assert "[second output replacement]" not in facts["both"] + facts["clean"]
    assert all("[stand-in Tirith warning]" not in row["input"] for row in facts["result_calls"])
    assert len(facts["output_calls"]) == 2
    foreground = facts["output_calls"][-1]["arguments"]
    assert set(foreground) == {
        "command",
        "output",
        "returncode",
        "task_id",
        "env_type",
        "tool_call_id",
        "telemetry_schema_version",
    }
    assert foreground["command"] == "echo ok"
    assert foreground["returncode"] == 0
    assert foreground["task_id"] == "default"
    assert "[early output note]" in facts["background"]
    assert "[second output replacement]" not in facts["background"]
