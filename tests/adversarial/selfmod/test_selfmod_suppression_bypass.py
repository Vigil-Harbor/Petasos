"""Adversarial suppression bypass tests for selfmod (PET-164 Decision 3/4/5/6)."""
from __future__ import annotations

import os
import time
from pathlib import Path
from types import MappingProxyType

import pytest

from petasos._types import ScanFinding, Severity
from petasos.config import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.session.frequency import FrequencyTracker
from petasos.session.guard import ToolCallGuard


@pytest.fixture()
def owned_path(tmp_path: Path) -> str:
    p = tmp_path / "profiles" / "gibson" / "config.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch()
    return os.path.normcase(str(p.resolve(strict=False)))


def _make_guard(config: PetasosConfig, profile=None, owned_path: str = ""):
    pipeline = Pipeline(config=config, host_id="test-host")
    tracker = FrequencyTracker(config)
    guard = ToolCallGuard(pipeline, tracker, config, profile)
    if owned_path:
        guard._selfmod_owned_cache = (time.monotonic() + 9999, frozenset({owned_path}))
    return pipeline, guard, tracker


class TestFrequencyWeightFloors:
    """frequency_weights zeroing (glob and exact) -> floors hold."""

    @pytest.mark.anyio
    async def test_exact_zero_weight_floors_hold(self, owned_path: str):
        config = PetasosConfig(frequency_weights={
            "petasos.selfmod.config_write": 0.0,
            "petasos.selfmod.config_ref": 0.0,
        })
        _, guard, tracker = _make_guard(config, owned_path=owned_path)
        result = await guard.evaluate("write_file", {"path": owned_path}, "s1")
        assert result.selfmod_finding is not None
        assert result.selfmod_finding.rule_id == "petasos.selfmod.config_write"
        state = tracker.get_state("s1")
        assert state is not None
        assert state.last_score >= 10.0

    @pytest.mark.anyio
    async def test_glob_zero_weight_floors_hold(self, owned_path: str):
        config = PetasosConfig(frequency_weights={
            "petasos.selfmod.*": 0.0,
        })
        _, guard, tracker = _make_guard(config, owned_path=owned_path)
        result = await guard.evaluate("write_file", {"path": owned_path}, "s1")
        assert result.selfmod_finding is not None
        state = tracker.get_state("s1")
        assert state is not None
        assert state.last_score >= 10.0


class TestAlertBypasses:
    """alert_enabled: false -> selfmod alert still delivered."""

    @pytest.mark.anyio
    async def test_alert_enabled_false_still_delivers(self, owned_path: str):
        alerts = []
        config = PetasosConfig(alert_enabled=False)
        pipeline, guard, tracker = _make_guard(config, owned_path=owned_path)
        pipeline.add_alert_listener(lambda a: alerts.append(a))
        await guard.evaluate("write_file", {"path": owned_path}, "s1")
        assert any(a.rule_id == "selfmod_attempt" for a in alerts)

    @pytest.mark.anyio
    async def test_frequency_enabled_false_still_records(self, owned_path: str):
        config = PetasosConfig(frequency_enabled=False)
        _, guard, tracker = _make_guard(config, owned_path=owned_path)
        await guard.evaluate("write_file", {"path": owned_path}, "s1")
        state = tracker.get_state("s1")
        assert state is not None
        assert state.last_score >= 10.0


class TestInflatedThresholds:
    """Inflated thresholds / near-zero half-life -> alert + receipt still fire."""

    @pytest.mark.anyio
    async def test_inflated_thresholds_alert_fires(self, owned_path: str):
        alerts = []
        config = PetasosConfig(
            tier1_threshold=1e9,
            tier2_threshold=1e9 + 1,
            tier3_threshold=1e9 + 2,
        )
        pipeline, guard, tracker = _make_guard(config, owned_path=owned_path)
        pipeline.add_alert_listener(lambda a: alerts.append(a))
        await guard.evaluate("write_file", {"path": owned_path}, "s1")
        assert any(a.rule_id == "selfmod_attempt" for a in alerts)
        assert guard._selfmod_owned_cache[1]  # owned set not empty


class TestProfileSuppression:
    """Profile suppress_rules with selfmod ids -> stripped at parse."""

    def test_suppress_rules_strips_selfmod(self):
        from petasos.session.profiles import ResolvedProfile

        profile = ResolvedProfile(
            name="test",
            suppress_rules=frozenset({"petasos.selfmod.config_write", "petasos.selfmod.config_ref"}),
            severity_overrides=MappingProxyType({}),
            confidence_floor=0.0,
            tier_thresholds=None,
            pii_entities_extra=(),
            tool_exempt_list=frozenset(),
            tool_alias_map=MappingProxyType({}),
        )
        assert "petasos.selfmod.config_write" not in profile.suppress_rules
        assert "petasos.selfmod.config_ref" not in profile.suppress_rules


class TestSeverityOverrideRefused:
    """severity_overrides downgrade attempt -> refused (floor rule)."""

    def test_selfmod_is_floor_rule(self):
        from petasos.pipeline import _is_floor_rule
        assert _is_floor_rule("petasos.selfmod.config_write") is True
        assert _is_floor_rule("petasos.selfmod.config_ref") is True
        assert _is_floor_rule("petasos.selfmod.console_probe") is True


class TestBuiltInProfilesDetectionSurvives:
    """Every built-in profile applied -> detection still fires."""

    @pytest.mark.anyio
    @pytest.mark.parametrize("profile_name", ["general", "customer_service", "code_generation", "research", "admin"])
    async def test_builtin_profile_detection(self, owned_path: str, profile_name: str):
        from petasos.session.profiles import ProfileResolver
        resolver = ProfileResolver()
        profile = resolver.resolve(profile_name)
        config = PetasosConfig()
        pipeline = Pipeline(config=config, host_id="test-host")
        tracker = FrequencyTracker(config)
        guard = ToolCallGuard(pipeline, tracker, config, profile)
        guard._selfmod_owned_cache = (time.monotonic() + 9999, frozenset({owned_path}))
        result = await guard.evaluate("write_file", {"path": owned_path}, "s1")
        assert result.selfmod_finding is not None
        assert result.selfmod_finding.rule_id == "petasos.selfmod.config_write"
