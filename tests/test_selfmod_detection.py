"""Behavioral tests for the selfmod detection system (PET-164).

Covers: config_write classification, config_ref classification, read-only
exclusion, hostile alias-map bypass resistance, adversarial arg shapes,
side-effect-free verdict, record_selfmod fault tolerance, nested arg
detection, and GuardResult serialization of selfmod fields.
"""

from __future__ import annotations

import os
import time
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest

from petasos._types import ScanFinding, Severity
from petasos.config import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.session.frequency import FrequencyTracker
from petasos.session.guard import SELFMOD_DEPTH_OVERFLOW_TARGET, ToolCallGuard
from petasos.session.profiles import ResolvedProfile

if TYPE_CHECKING:
    from pathlib import Path

_GuardPair = tuple[Pipeline, ToolCallGuard, FrequencyTracker, str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(**overrides: object) -> PetasosConfig:
    defaults: dict[str, object] = {
        "frequency_enabled": True,
        "escalation_enabled": True,
        "tool_guard_enabled": True,
    }
    defaults.update(overrides)
    return PetasosConfig(**defaults)  # type: ignore[arg-type]


def _denormalize(normcased_path: str) -> str:
    """Convert a normcased path back to a plausible form for test args."""
    return normcased_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def owned_path(tmp_path: Path) -> str:
    """A fake owned config path with enough depth to pass hygiene."""
    p = tmp_path / "profiles" / "gibson" / "config.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch()
    return os.path.normcase(str(p.resolve(strict=False)))


@pytest.fixture()
def guard_pair(owned_path: str) -> _GuardPair:
    """Pipeline + guard with the guard's tracker, patched owned set."""
    config = _cfg()
    pipeline = Pipeline(config=config)
    tracker = FrequencyTracker(config)
    guard = ToolCallGuard(pipeline, tracker, config)
    # Patch the owned-set cache to return our known path
    guard._selfmod_owned_cache = (time.monotonic() + 9999, frozenset({owned_path}))
    return pipeline, guard, tracker, owned_path


# ---------------------------------------------------------------------------
# config_write classification
# ---------------------------------------------------------------------------


class TestConfigWriteClassification:
    """Write tool where top-level arg equals owned path -> config_write (CRITICAL)."""

    async def test_write_file_top_level_arg_equals_owned(self, guard_pair: _GuardPair) -> None:
        pipeline, guard, tracker, owned = guard_pair
        result = await guard.evaluate(
            "write_file", {"path": _denormalize(owned), "content": "evil"}, "s1"
        )
        assert result.selfmod_finding is not None
        assert result.selfmod_finding.rule_id == "petasos.selfmod.config_write"
        assert result.selfmod_finding.severity == Severity.CRITICAL
        assert result.selfmod_target == owned
        # Finding NOT in the main findings tuple
        assert result.selfmod_finding not in result.findings

    async def test_file_write_alias_also_classifies(self, guard_pair: _GuardPair) -> None:
        """file_write (alias for write) still triggers config_write."""
        pipeline, guard, tracker, owned = guard_pair
        result = await guard.evaluate(
            "file_write", {"path": _denormalize(owned), "content": "evil"}, "s1"
        )
        assert result.selfmod_finding is not None
        assert result.selfmod_finding.rule_id == "petasos.selfmod.config_write"


# ---------------------------------------------------------------------------
# config_ref classification
# ---------------------------------------------------------------------------


class TestConfigRefClassification:
    """Content mention or shell reference -> config_ref (HIGH)."""

    async def test_content_mention_is_config_ref(self, guard_pair: _GuardPair) -> None:
        pipeline, guard, tracker, owned = guard_pair
        result = await guard.evaluate(
            "write_file",
            {"path": "runbook.md", "content": f"see {_denormalize(owned)} for details"},
            "s1",
        )
        assert result.selfmod_finding is not None
        assert result.selfmod_finding.rule_id == "petasos.selfmod.config_ref"
        assert result.selfmod_finding.severity == Severity.HIGH

    async def test_shell_cat_is_config_ref(self, guard_pair: _GuardPair) -> None:
        pipeline, guard, tracker, owned = guard_pair
        result = await guard.evaluate("bash", {"command": f"cat {_denormalize(owned)}"}, "s1")
        assert result.selfmod_finding is not None
        assert result.selfmod_finding.rule_id == "petasos.selfmod.config_ref"

    async def test_powershell_get_content_is_config_ref(self, guard_pair: _GuardPair) -> None:
        pipeline, guard, tracker, owned = guard_pair
        result = await guard.evaluate(
            "bash", {"command": f"powershell Get-Content {_denormalize(owned)}"}, "s1"
        )
        assert result.selfmod_finding is not None
        assert result.selfmod_finding.rule_id == "petasos.selfmod.config_ref"

    async def test_delegate_task_prompt_is_config_ref(self, guard_pair: _GuardPair) -> None:
        pipeline, guard, tracker, owned = guard_pair
        result = await guard.evaluate(
            "delegate_task",
            {"prompt": f"Edit the file at {_denormalize(owned)} and remove the guard"},
            "s1",
        )
        assert result.selfmod_finding is not None
        assert result.selfmod_finding.rule_id == "petasos.selfmod.config_ref"

    async def test_nested_arg_config_ref(self, guard_pair: _GuardPair) -> None:
        pipeline, guard, tracker, owned = guard_pair
        result = await guard.evaluate(
            "delegate_task",
            {"files": [{"path": _denormalize(owned)}]},
            "s1",
        )
        assert result.selfmod_finding is not None
        assert result.selfmod_finding.rule_id == "petasos.selfmod.config_ref"


# ---------------------------------------------------------------------------
# Read-only exclusion (pre-alias space pin)
# ---------------------------------------------------------------------------


class TestReadOnlyExclusion:
    """read_file + owned path -> no finding."""

    async def test_read_file_no_classification(self, guard_pair: _GuardPair) -> None:
        pipeline, guard, tracker, owned = guard_pair
        result = await guard.evaluate("read_file", {"path": _denormalize(owned)}, "s1")
        assert result.selfmod_finding is None
        assert result.selfmod_target is None

    async def test_search_no_classification(self, guard_pair: _GuardPair) -> None:
        """search is read-only, should not trigger selfmod."""
        pipeline, guard, tracker, owned = guard_pair
        result = await guard.evaluate(
            "search", {"query": "secret", "path": _denormalize(owned)}, "s1"
        )
        assert result.selfmod_finding is None

    async def test_web_search_no_classification(self, guard_pair: _GuardPair) -> None:
        """web_search is read-only, should not trigger selfmod."""
        pipeline, guard, tracker, owned = guard_pair
        result = await guard.evaluate("web_search", {"query": _denormalize(owned)}, "s1")
        assert result.selfmod_finding is None


# ---------------------------------------------------------------------------
# Hostile alias map resistance
# ---------------------------------------------------------------------------


class TestHostileAliasMap:
    """Profile tool_alias_map that maps write_file -> read_file must NOT
    defeat the classification; the pre-alias canonical form is what the
    selfmod classifier inspects."""

    async def test_hostile_alias_map_still_classifies(self, owned_path: str) -> None:
        config = _cfg()
        pipeline = Pipeline(config=config)
        tracker = FrequencyTracker(config)
        profile = ResolvedProfile(
            name="hostile",
            suppress_rules=frozenset(),
            severity_overrides=MappingProxyType({}),
            confidence_floor=0.0,
            tier_thresholds=None,
            pii_entities_extra=(),
            tool_exempt_list=frozenset(),
            tool_alias_map=MappingProxyType({"write_file": "read_file"}),
        )
        guard = ToolCallGuard(pipeline, tracker, config, profile)
        guard._selfmod_owned_cache = (
            time.monotonic() + 9999,
            frozenset({owned_path}),
        )
        result = await guard.evaluate("write_file", {"path": _denormalize(owned_path)}, "s1")
        assert result.selfmod_finding is not None
        assert result.selfmod_finding.rule_id == "petasos.selfmod.config_write"


# ---------------------------------------------------------------------------
# Adversarial arg shapes
# ---------------------------------------------------------------------------


class TestAdversarialArgShapes:
    """bytes values, non-str keys, deep nesting -> no exception,
    allowed/reason identical to baseline."""

    async def test_bytes_value_no_exception(self, guard_pair: _GuardPair) -> None:
        pipeline, guard, tracker, owned = guard_pair
        result_baseline = await guard.evaluate("write_file", {"path": "safe.txt"}, "s1")
        result = await guard.evaluate(
            "write_file",
            {"path": b"bytes-value"},
            "s2",
        )
        assert result.allowed == result_baseline.allowed
        assert result.reason == result_baseline.reason

    async def test_non_str_keys_no_exception(self, guard_pair: _GuardPair) -> None:
        pipeline, guard, tracker, owned = guard_pair
        result_baseline = await guard.evaluate("write_file", {"path": "safe.txt"}, "s1")
        result = await guard.evaluate(
            "write_file",
            {123: "non-str-key"},  # type: ignore[dict-item]
            "s2",
        )
        assert result.allowed == result_baseline.allowed
        assert result.reason == result_baseline.reason

    async def test_deep_nesting_no_exception(self, guard_pair: _GuardPair) -> None:
        pipeline, guard, tracker, owned = guard_pair
        result_baseline = await guard.evaluate("write_file", {"path": "safe.txt"}, "s1")
        evil_params = {
            "path": b"bytes-value",
            123: "non-str-key",
            "nested": {"deep": {"deeper": owned}},
        }
        result = await guard.evaluate(
            "write_file",
            evil_params,  # type: ignore[arg-type]
            "s2",
        )
        assert result.allowed == result_baseline.allowed
        assert result.reason == result_baseline.reason

    async def test_none_values_no_exception(self, guard_pair: _GuardPair) -> None:
        pipeline, guard, tracker, owned = guard_pair
        result = await guard.evaluate("write_file", {"path": None, "content": None}, "s1")
        # Should not raise; selfmod_finding should be None (no path-like values)
        assert result.selfmod_finding is None


# ---------------------------------------------------------------------------
# Side-effect-free on current call
# ---------------------------------------------------------------------------


class TestSideEffectFree:
    """The selfmod classification does not change allow/deny on the current call."""

    async def test_verdict_identical_with_and_without_owned_path(
        self, guard_pair: _GuardPair
    ) -> None:
        pipeline, guard, tracker, owned = guard_pair
        # Evaluate without the owned path -> baseline
        baseline = await guard.evaluate("write_file", {"path": "safe.txt", "content": "ok"}, "s1")
        # Evaluate with the owned path -> selfmod classified but same verdict
        result = await guard.evaluate(
            "write_file", {"path": _denormalize(owned), "content": "ok"}, "s2"
        )
        assert result.allowed == baseline.allowed
        assert result.reason == baseline.reason
        assert result.tier == baseline.tier


# ---------------------------------------------------------------------------
# record_selfmod never throws
# ---------------------------------------------------------------------------


class TestRecordSelfmodFaultTolerance:
    """record_selfmod never throws even with broken internals."""

    async def test_record_selfmod_with_broken_audit_emitter(self, guard_pair: _GuardPair) -> None:
        pipeline, guard, tracker, owned = guard_pair
        finding = ScanFinding(
            rule_id="petasos.selfmod.config_write",
            finding_type="selfmod",
            severity=Severity.CRITICAL,
            confidence=1.0,
            message="test",
            scanner_name="tool_guard",
        )
        # Break the audit emitter
        pipeline._audit_emitter = None  # type: ignore[assignment]
        # Should not raise
        pipeline.record_selfmod("s1", finding)

    async def test_record_selfmod_with_broken_alert_manager(self, guard_pair: _GuardPair) -> None:
        pipeline, guard, tracker, owned = guard_pair
        finding = ScanFinding(
            rule_id="petasos.selfmod.config_write",
            finding_type="selfmod",
            severity=Severity.CRITICAL,
            confidence=1.0,
            message="test",
            scanner_name="tool_guard",
        )
        # Break the alert manager
        pipeline._alert_manager = None  # type: ignore[assignment]
        # Should not raise
        pipeline.record_selfmod("s1", finding)

    async def test_record_selfmod_with_none_session_id(self, guard_pair: _GuardPair) -> None:
        pipeline, guard, tracker, owned = guard_pair
        finding = ScanFinding(
            rule_id="petasos.selfmod.config_ref",
            finding_type="selfmod",
            severity=Severity.HIGH,
            confidence=1.0,
            message="test",
            scanner_name="tool_guard",
        )
        # None session_id should not raise
        pipeline.record_selfmod(None, finding)


# ---------------------------------------------------------------------------
# Depth-overflow fail-secure marker
# ---------------------------------------------------------------------------


class TestDepthOverflowMarker:
    """Over-cap nesting flags fail-secure with the sentinel target, never a
    fabricated owned path (the overflow means nothing was actually matched)."""

    async def test_overflow_records_sentinel_not_owned_path(self, guard_pair: _GuardPair) -> None:
        pipeline, guard, tracker, owned = guard_pair
        deep: object = "innocuous"
        for _ in range(40):
            deep = {"k": deep}
        result = await guard.evaluate("delegate_task", {"payload": deep}, "s1")
        assert result.selfmod_finding is not None
        assert result.selfmod_finding.rule_id == "petasos.selfmod.config_ref"
        assert result.selfmod_target == SELFMOD_DEPTH_OVERFLOW_TARGET
        assert owned not in result.selfmod_finding.message
        assert "depth cap" in result.selfmod_finding.message
        assert "no owned path matched" in result.selfmod_finding.message

    async def test_overflow_via_list_nesting(self, guard_pair: _GuardPair) -> None:
        pipeline, guard, tracker, owned = guard_pair
        deep: object = ["benign/with/slash"]
        for _ in range(40):
            deep = [deep]
        result = await guard.evaluate("delegate_task", {"payload": deep}, "s1")
        assert result.selfmod_finding is not None
        assert result.selfmod_target == SELFMOD_DEPTH_OVERFLOW_TARGET

    async def test_matched_path_message_still_names_target(self, guard_pair: _GuardPair) -> None:
        pipeline, guard, tracker, owned = guard_pair
        result = await guard.evaluate(
            "write_file", {"path": _denormalize(owned), "content": "x"}, "s1"
        )
        assert result.selfmod_finding is not None
        assert owned in result.selfmod_finding.message
        assert SELFMOD_DEPTH_OVERFLOW_TARGET not in result.selfmod_finding.message


# ---------------------------------------------------------------------------
# GuardResult serialization
# ---------------------------------------------------------------------------


class TestGuardResultSerialization:
    """GuardResult.to_dict() includes selfmod fields."""

    async def test_to_dict_includes_selfmod_fields(self, guard_pair: _GuardPair) -> None:
        pipeline, guard, tracker, owned = guard_pair
        result = await guard.evaluate("write_file", {"path": _denormalize(owned)}, "s1")
        d = result.to_dict()
        assert "selfmod_target" in d
        assert "selfmod_finding" in d
        assert d["selfmod_target"] == owned

    async def test_to_dict_selfmod_finding_none_when_absent(self, guard_pair: _GuardPair) -> None:
        pipeline, guard, tracker, owned = guard_pair
        result = await guard.evaluate("write_file", {"path": "safe.txt"}, "s1")
        d = result.to_dict()
        assert d["selfmod_target"] is None
        assert d["selfmod_finding"] is None

    async def test_to_dict_selfmod_finding_is_dict_when_present(
        self, guard_pair: _GuardPair
    ) -> None:
        pipeline, guard, tracker, owned = guard_pair
        result = await guard.evaluate(
            "write_file", {"path": _denormalize(owned), "content": "x"}, "s1"
        )
        d = result.to_dict()
        assert isinstance(d["selfmod_finding"], dict)
        assert d["selfmod_finding"]["rule_id"] == "petasos.selfmod.config_write"
        assert d["selfmod_finding"]["severity"] == "critical"
