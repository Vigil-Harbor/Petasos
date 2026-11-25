"""v0.23.3 wrapper hooks, unread allowlists and approval-policy handoff."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.hermes_host.client import Sandbox, call
from tests.hermes_host.marks import requires_hermes_sandbox

pytestmark = requires_hermes_sandbox
_HARNESS = Path(__file__).with_name("single_ask_harness.py")


def _run(installed: Sandbox, case: str) -> dict[str, Any]:
    return call(installed, {"case": case}, harness=_HARNESS, timeout=180)


@pytest.mark.parametrize("case", ["wrapper", "wrapper_ask"])
def test_tool_search_asks_and_scores_once(installed: Sandbox, case: str) -> None:
    result = _run(installed, case)
    assert len(result["prompts"]) == 1
    assert result["guardian"] == []
    assert [row["tool"] for row in result["fires"]] == ["tool_call", "terminal"]
    first, second = result["fires"]
    assert first["after"] > first["before"]
    assert second["after"] == first["after"] == second["before"]
    assert not first["blocked"] and not second["blocked"]


def test_unread_allowlisted_command_still_asks_one_person(installed: Sandbox) -> None:
    result = _run(installed, "unread")
    assert result["judge"] == "person"
    assert len(result["prompts"]) == 1
    requests = [row for row in result["approvals"] if row["phase"] == "request"]
    assert len(requests) == 1
    assert not requests[0]["rule_id"].startswith("plugin_rule:")
    assert result["guardian"] == []
    assert result["executed"] == []


@pytest.mark.parametrize("case", ["policy", "policy_quote"])
def test_approval_settings_write_is_asked_once_by_hermes(installed: Sandbox, case: str) -> None:
    result = _run(installed, case)
    assert result["judge"] == "person"
    assert len(result["prompts"]) == 1
    requests = [row for row in result["approvals"] if row["phase"] == "request"]
    assert len(requests) == 1
    assert not requests[0]["rule_id"].startswith("plugin_rule:")
    assert result["guardian"] == []
    assert result["executed"] == []
    assert result["guardrail"][-1]["decision"] == "deferred"
    assert result["fires"][0]["after"] > result["fires"][0]["before"]
