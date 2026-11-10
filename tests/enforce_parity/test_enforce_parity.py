"""Replay the enforcement corpus and fail when an outcome differs."""

from __future__ import annotations

import difflib
import json
from typing import Any

import pytest

from tests.enforce_parity.load import (
    OUTCOMES_PATH,
    SCENARIOS_PATH,
    dump_outcomes,
    expand_scenario,
    load_json,
)
from tests.enforce_parity.plugin_adapter import PluginOracle

_MAX_DIFFS = 8

# Every situation the corpus claims to pin. A new scenario should add to this
# only when it covers a behaviour the list does not already name.
_REQUIRED = frozenset(
    {
        "always-approved",
        "approval-answer",
        "approval-confirm",
        "approval-deny",
        "approval-request",
        "approve-unavailable",
        "arm",
        "auto-approve",
        "clean",
        "dangerous",
        "degraded-approve",
        "disarm",
        "disarmed",
        "excerpt-invisible",
        "excerpt-long",
        "excerpt-secret",
        "fanout",
        "fanout-tier",
        "guard-error",
        "guard-timeout",
        "ingest",
        "init-completes",
        "init-failed-closed",
        "init-failed-degraded",
        "init-failed-open",
        "lineage",
        "lineage-unavailable",
        "non-ingest",
        "pii-egress",
        "pii-internal",
        "posture-approve",
        "posture-block",
        "profile-admin",
        "profile-change",
        "profile-code_generation",
        "profile-customer_service",
        "profile-general",
        "profile-research",
        "read-only",
        "ready",
        "result-clean",
        "result-credential",
        "result-error",
        "result-finding",
        "result-oversized",
        "result-timeout",
        "result-unmatched",
        "selfmod",
        "settings-invalid",
        "settings-live",
        "settings-restart",
        "sink-variant",
        "starting",
        "syntactic-command",
        "syntactic-encoding",
        "syntactic-injection",
        "syntactic-structural",
        "taint-egress",
        "taint-internal",
        "taint-short",
        "taint-source",
        "tier1",
        "tier2",
        "tier3",
    }
)

_VOLATILE = frozenset({"scan_id", "sig", "timestamp"})


def _scenarios() -> list[dict[str, Any]]:
    corpus = load_json(SCENARIOS_PATH)
    scenarios = corpus.get("scenarios")
    if not isinstance(scenarios, list):
        raise TypeError("scenarios must be a list")
    return [item for item in scenarios if isinstance(item, dict)]


def _ids() -> list[str]:
    return [str(item["id"]) for item in _scenarios()]


def _step_diff(expected: object, actual: object) -> str:
    expected_lines = json.dumps(expected, indent=2, sort_keys=True).splitlines()
    actual_lines = json.dumps(actual, indent=2, sort_keys=True).splitlines()
    return "\n".join(
        difflib.unified_diff(
            expected_lines,
            actual_lines,
            fromfile="recorded",
            tofile="actual",
            lineterm="",
        )
    )


def _walk(node: object, found: set[str]) -> None:
    if isinstance(node, dict):
        found.update(key for key in node if key in _VOLATILE)
        for value in node.values():
            _walk(value, found)
    elif isinstance(node, list):
        for item in node:
            _walk(item, found)


@pytest.mark.parametrize("scenario_id", _ids())
def test_scenario_matches_record(scenario_id: str) -> None:
    """The live plugin outcomes for one scenario equal the committed record."""
    recorded = load_json(OUTCOMES_PATH)
    scenarios = recorded.get("scenarios")
    if not isinstance(scenarios, dict) or scenario_id not in scenarios:
        raise AssertionError(f"{scenario_id} is missing from outcomes.json")
    scenario = next(item for item in _scenarios() if item["id"] == scenario_id)
    actual = PluginOracle().replay(expand_scenario(scenario))
    expected = scenarios[scenario_id]
    if actual == expected:
        return
    diffs: list[str] = []
    if not isinstance(expected, list):
        raise AssertionError(f"{scenario_id} recorded outcomes are not a list")
    pairs = max(len(expected), len(actual))
    for index in range(pairs):
        left = expected[index] if index < len(expected) else None
        right = actual[index] if index < len(actual) else None
        if left == right:
            continue
        step_id = ""
        if isinstance(right, dict):
            step_id = str(right.get("id", ""))
        elif isinstance(left, dict):
            step_id = str(left.get("id", ""))
        diffs.append(f"{scenario_id} step={step_id or index}\n{_step_diff(left, right)}")
        if len(diffs) >= _MAX_DIFFS:
            break
    extra = ""
    if len(diffs) >= _MAX_DIFFS:
        extra = f"\n(stopped after {_MAX_DIFFS} differing steps)"
    raise AssertionError(
        "enforcement outcomes differ from tests/enforce_parity/outcomes.json\n\n"
        + "\n\n".join(diffs)
        + extra
    )


def test_record_is_canonical() -> None:
    """The committed file is the one-step-per-line serialisation."""
    raw = OUTCOMES_PATH.read_text(encoding="utf-8")
    assert raw == dump_outcomes(json.loads(raw))


def test_each_step_occupies_one_line() -> None:
    """A diff of the record can show one step without neighbouring noise."""
    raw = OUTCOMES_PATH.read_text(encoding="utf-8")
    for scenario in _scenarios():
        scenario_id = str(scenario["id"])
        marker = f"    {json.dumps(scenario_id)}: ["
        start = raw.find(marker)
        assert start != -1, scenario_id
        rest = raw[start + len(marker) :]
        end = rest.find("\n    ]")
        block = rest[:end]
        for step in expand_scenario(scenario)["steps"]:
            needle = f'"id":"{step["id"]}"'
            hits = [line for line in block.splitlines() if needle in line]
            assert len(hits) == 1, f"{scenario_id} {step['id']}"


def test_categories_are_covered() -> None:
    """The corpus names every situation this oracle exists to pin."""
    found: set[str] = set()
    for scenario in _scenarios():
        categories = scenario.get("categories", [])
        if not isinstance(categories, list):
            raise TypeError("categories must be a list")
        for category in categories:
            if not isinstance(category, str):
                raise TypeError("category must be a string")
            found.add(category)
    missing = sorted(_REQUIRED - found)
    assert not missing, "scenarios never cover: " + ", ".join(missing)


def test_record_drops_volatile_event_fields() -> None:
    """Timestamps, scan ids and signatures are not part of the record."""
    found: set[str] = set()
    _walk(load_json(OUTCOMES_PATH), found)
    assert not found, "volatile event fields in the record: " + ", ".join(sorted(found))
