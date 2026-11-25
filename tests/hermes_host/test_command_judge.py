"""The ask predicate against Hermes's live command gate.

Skipped unless ``PETASOS_HERMES_SANDBOX`` names a prepared sandbox. Command
strings are passed to functions. Nothing is executed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.hermes_host.client import Sandbox, call, fresh_home
from tests.hermes_host.marks import requires_hermes_sandbox

pytestmark = requires_hermes_sandbox

_HARNESS = Path(__file__).resolve().parent / "ask_harness.py"


@pytest.fixture(scope="module")
def rows(petasos_wheel: Path) -> dict[str, dict[str, Any]]:
    home = fresh_home(petasos_wheel, "command-judge")
    result = call(
        Sandbox(petasos_wheel, home),
        {"action": "ask"},
        harness=_HARNESS,
        timeout=180,
    )
    found = result["cases"]
    assert isinstance(found, list)
    return {str(row["name"]): row for row in found}


def test_where_the_gate_prompts_the_judge_is_a_person(rows: dict[str, dict[str, Any]]) -> None:
    for name in ("interactive", "docker_host"):
        row = rows[name]
        assert row["prompted"] is True, name
        assert row["approved"] is False, name
        assert row["judge"] == "person", name


def test_where_the_gate_approves_without_asking_the_judge_is_nobody(
    rows: dict[str, dict[str, Any]],
) -> None:
    for name in (
        "benign",
        "petasos_only",
        "headless",
        "mode_off",
        "yolo",
        "cron_approve",
        "single_query_approve",
        "unattended_approve",
        "docker",
        "docker_hardline",
    ):
        row = rows[name]
        assert row["approved"] is True, name
        assert row["prompted"] is False, name
        assert row["judge"] == "nobody", name


def test_smart_mode_has_a_guardian(rows: dict[str, dict[str, Any]]) -> None:
    """Both guardian outcomes have the same host owner before judgment."""
    approves = rows["smart_approves"]
    assert approves["approved"] is True
    assert approves["prompted"] is False
    assert approves["judge"] == "guardian_then_person"
    escalates = rows["smart_escalates"]
    assert escalates["prompted"] is True
    assert escalates["judge"] == "guardian_then_person"


def test_a_hardline_refusal_is_not_an_ask(rows: dict[str, dict[str, Any]]) -> None:
    row = rows["hardline"]
    assert row["approved"] is False
    assert row["prompted"] is False
    assert row["judge"] == "nobody"
    denied = rows["cron_deny"]
    assert denied["approved"] is False
    assert denied["prompted"] is False
    assert denied["judge"] == "nobody"


def test_a_missing_or_raising_detector_answers_no(rows: dict[str, dict[str, Any]]) -> None:
    for name in ("raises", "missing"):
        row = rows[name]
        assert row["prompted"] is True, name
        assert row["judge"] == "nobody", name
