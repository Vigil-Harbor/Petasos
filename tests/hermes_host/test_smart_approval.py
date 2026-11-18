"""A flagged terminal command reaches its configured judge exactly once."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.hermes_host.client import Sandbox, call
from tests.hermes_host.marks import requires_hermes_sandbox

pytestmark = requires_hermes_sandbox
_HARNESS = Path(__file__).with_name("smart_harness.py")


def _run(installed: Sandbox, **settings: Any) -> dict[str, Any]:
    return call(installed, settings, harness=_HARNESS, timeout=180)


@pytest.mark.parametrize("verdict", ["approve", "deny", "escalate"])
def test_smart_has_one_guardian_judgment_and_one_deferral(
    installed: Sandbox, verdict: str
) -> None:
    result = _run(installed, verdict=verdict)
    assert len(result["guardian"]) == 1
    assert len(result["deferred"]) == 1
    event = result["deferred"][0]
    assert event["deferred_to"] == "Hermes's smart approval"
    assert event["tier"] == "none"
    assert event["score"] == 0.0
    assert event["rule_id"] == "petasos.syntactic.command.fetch-exec"
    assert all(not row["command"].startswith("<terminal>") for row in result["prompts"])
    if verdict == "approve":
        # Approval reaches the harness's execution tripwire, never a real command.
        assert "tripwire" in result["result"]
    else:
        assert result["executed"] == []
    if verdict == "escalate":
        assert len(result["prompts"]) == 1


def test_manual_still_has_one_persons_judgment(installed: Sandbox) -> None:
    result = _run(installed, mode="manual")
    assert result["guardian"] == []
    assert len(result["prompts"]) == 1
    assert not result["prompts"][0]["command"].startswith("<terminal>")
    assert len(result["deferred"]) == 1
    assert result["deferred"][0]["deferred_to"] == "Hermes"
    assert result["executed"] == []


@pytest.mark.parametrize("context", ["cron", "single_query"])
@pytest.mark.parametrize("context_mode", ["approve", "deny"])
def test_unattended_contexts_keep_petasos_decision(
    installed: Sandbox, context: str, context_mode: str
) -> None:
    result = _run(installed, context=context, context_mode=context_mode)
    assert result["guardian"] == []
    assert result["prompts"] == []
    assert result["deferred"] == []
    assert "command_gate" not in result["order"]
    assert result["executed"] == []


def test_at_tier1_petasos_asks_the_person_itself(installed: Sandbox) -> None:
    result = _run(installed, tier1=True)
    assert result["tier_before"] == "tier1"
    assert result["deferred"] == []
    assert result["prompts"][0]["command"].startswith("<terminal>")
    assert len(result["guardian"]) == 1
    assert result["executed"] == []
