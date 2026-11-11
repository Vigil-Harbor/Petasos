"""Replay the enforcement corpus and fail when an outcome differs."""

from __future__ import annotations

import difflib
import json
from typing import Any

import pytest

from tests.enforce_parity.enforcer_adapter import EnforcerOracle
from tests.enforce_parity.hermes_adapter import HermesOracle
from tests.enforce_parity.load import (
    OUTCOMES_PATH,
    SCENARIOS_PATH,
    dump_outcomes,
    expand_scenario,
    load_json,
)

_DIFFERENCES_PATH = OUTCOMES_PATH.parent / "differences.json"
_RECONFIGURED = "PETASOS_RECONFIGURED: live config.yaml change applied to the running session"

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


def _differences() -> list[dict[str, Any]]:
    document = load_json(_DIFFERENCES_PATH)
    rows = document.get("differences")
    if not isinstance(rows, list):
        raise TypeError("differences must be a list")
    return [row for row in rows if isinstance(row, dict)]


def _adapters_of(row: dict[str, Any]) -> list[str]:
    raw = row.get("adapters")
    if not isinstance(raw, list) or not raw or not all(isinstance(item, str) for item in raw):
        raise AssertionError("a difference must name the adapters it applies to")
    return list(raw)


def _rows_for(adapter: str) -> list[dict[str, Any]]:
    return [row for row in _differences() if adapter in _adapters_of(row)]


def _matches(pattern: str, value: str) -> bool:
    return pattern == "*" or pattern == value


def _apply_log(expected: dict[str, Any], actual: dict[str, Any], row: dict[str, Any]) -> bool:
    """Apply one listed log difference. True when this step exhibited it."""
    old = row.get("old")
    new = row.get("new")
    expected_logs = expected.get("logs")
    actual_logs = actual.get("logs")
    if not isinstance(expected_logs, list) or not isinstance(actual_logs, list):
        return False
    if isinstance(old, str) and new is None:
        if old not in expected_logs or old in actual_logs:
            return False
        # The empty-cache line is the first log of the steps it explains.
        # A later line with the same text is a real change and stays pinned.
        if row.get("scenario") == "*" and expected_logs[0] != old:
            return False
        expected_logs.remove(old)
        return True
    if old is None and isinstance(new, str):
        if new not in actual_logs or new in expected_logs:
            return False
        actual_logs.remove(new)
        return True
    if isinstance(old, str) and isinstance(new, str):
        if old not in expected_logs or new not in actual_logs or old in actual_logs:
            return False
        expected_logs[expected_logs.index(old)] = new
        return True
    return False


def _apply_differences(
    expected: dict[str, Any],
    actual: dict[str, Any],
    rows: list[dict[str, Any]],
    scenario_id: str,
    step_id: str,
    used: set[int],
) -> None:
    for index, row in enumerate(rows):
        scenario = row.get("scenario")
        step = row.get("step")
        if not isinstance(scenario, str) or not isinstance(step, str):
            continue
        if not _matches(scenario, scenario_id) or not _matches(step, step_id):
            continue
        # A row that names no scenario explains one step per scenario at most.
        # Without this limit it could hide the same line going missing later.
        if scenario == "*" and index in used:
            continue
        if row.get("field") == "logs" and _apply_log(expected, actual, row):
            used.add(index)


@pytest.mark.parametrize("scenario_id", _ids())
def _compare(scenario_id: str, actual: list[Any], adapter: str) -> None:
    """Fail when ``actual`` differs from the record after that adapter's rows."""
    recorded = load_json(OUTCOMES_PATH)
    scenarios = recorded.get("scenarios")
    if not isinstance(scenarios, dict) or scenario_id not in scenarios:
        raise AssertionError(f"{scenario_id} is missing from outcomes.json")
    expected = scenarios[scenario_id]
    if not isinstance(expected, list):
        raise AssertionError(f"{scenario_id} recorded outcomes are not a list")
    rows = _rows_for(adapter)
    used: set[int] = set()
    compared_expected: list[dict[str, Any]] = []
    compared_actual: list[dict[str, Any]] = []
    pairs = max(len(expected), len(actual))
    for index in range(pairs):
        left = expected[index] if index < len(expected) else None
        right = actual[index] if index < len(actual) else None
        if isinstance(left, dict) and isinstance(right, dict):
            left = json.loads(json.dumps(left))
            right = json.loads(json.dumps(right))
            step_id = str(right.get("id", left.get("id", index)))
            _apply_differences(left, right, rows, scenario_id, step_id, used)
        compared_expected.append(left if isinstance(left, dict) else {"id": index})
        compared_actual.append(right if isinstance(right, dict) else {"id": index})
    if compared_expected == compared_actual:
        return
    diffs: list[str] = []
    for index in range(pairs):
        left = compared_expected[index] if index < len(compared_expected) else None
        right = compared_actual[index] if index < len(compared_actual) else None
        if left == right:
            continue
        step_id = ""
        if isinstance(right, dict):
            step_id = str(right.get("id", ""))
        diffs.append(f"{scenario_id} step={step_id or index}\n{_step_diff(left, right)}")
        if len(diffs) >= _MAX_DIFFS:
            break
    raise AssertionError(
        f"{adapter} outcomes differ from the record after listed differences\n\n"
        + "\n\n".join(diffs)
    )


@pytest.mark.parametrize("scenario_id", _ids())
def test_enforcer_matches_record(scenario_id: str) -> None:
    """The enforcer matches the record except the differences listed for it."""
    scenario = next(item for item in _scenarios() if item["id"] == scenario_id)
    actual = EnforcerOracle().replay(expand_scenario(scenario))
    _compare(scenario_id, actual, "enforcer")


@pytest.mark.parametrize("scenario_id", _ids())
def test_hermes_adapter_matches_record(scenario_id: str) -> None:
    """The Hermes hooks match the record except the differences listed for them."""
    scenario = next(item for item in _scenarios() if item["id"] == scenario_id)
    actual = HermesOracle().replay(expand_scenario(scenario))
    _compare(scenario_id, actual, "hermes")


def _used_rows(adapter: str, replay: Any) -> set[int]:
    rows = _rows_for(adapter)
    used: set[int] = set()
    recorded = load_json(OUTCOMES_PATH)
    scenarios = recorded.get("scenarios")
    if not isinstance(scenarios, dict):
        raise AssertionError("outcomes scenarios must be an object")
    for scenario in _scenarios():
        scenario_id = str(scenario["id"])
        expected = scenarios[scenario_id]
        actual = replay(expand_scenario(scenario))
        if not isinstance(expected, list):
            continue
        for index in range(min(len(expected), len(actual))):
            left = expected[index]
            right = actual[index]
            if not isinstance(left, dict) or not isinstance(right, dict):
                continue
            left = json.loads(json.dumps(left))
            right = json.loads(json.dumps(right))
            step_id = str(right.get("id", ""))
            _apply_differences(left, right, rows, scenario_id, step_id, used)
    return used


@pytest.mark.parametrize("adapter", ["enforcer", "hermes"])
def test_listed_differences_all_occur(adapter: str) -> None:
    """A listed difference that this adapter does not exhibit fails the run."""
    rows = _rows_for(adapter)
    oracle = EnforcerOracle() if adapter == "enforcer" else HermesOracle()
    used = _used_rows(adapter, oracle.replay)
    missing = [rows[index]["reason"] for index in range(len(rows)) if index not in used]
    assert not missing, f"{adapter} listed differences that did not occur:\n" + "\n".join(missing)


def test_record_drops_volatile_event_fields() -> None:
    """Timestamps, scan ids and signatures are not part of the record."""
    found: set[str] = set()
    _walk(load_json(OUTCOMES_PATH), found)
    assert not found, "volatile event fields in the record: " + ", ".join(sorted(found))
