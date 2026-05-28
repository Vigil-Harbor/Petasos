from __future__ import annotations

import dataclasses
import time
from types import MappingProxyType
from unittest.mock import patch

import pytest

from petasos._types import Alert, PipelineResult, ScanFinding, Severity
from petasos.config import PetasosConfig
from petasos.premium.alerting import AlertManager
from petasos.premium.frequency import FrequencyUpdateResult


def _cfg(**overrides: object) -> PetasosConfig:
    defaults: dict[str, object] = {
        "alert_enabled": True,
        "frequency_enabled": True,
        "escalation_enabled": True,
    }
    defaults.update(overrides)
    return PetasosConfig(**defaults)  # type: ignore[arg-type]


def _result(
    *,
    safe: bool = True,
    findings: tuple[ScanFinding, ...] = (),
) -> PipelineResult:
    return PipelineResult(safe=safe, findings=findings)


def _finding(
    rule_id: str = "test.rule",
    finding_type: str = "injection",
    severity: Severity = Severity.HIGH,
    confidence: float = 0.9,
) -> ScanFinding:
    return ScanFinding(
        rule_id=rule_id,
        finding_type=finding_type,
        severity=severity,
        confidence=confidence,
        message="test",
        scanner_name="minimal",
    )


def _freq(
    previous_score: float = 0.0,
    current_score: float = 10.0,
    tier: str = "none",
) -> FrequencyUpdateResult:
    return FrequencyUpdateResult(
        previous_score=previous_score,
        current_score=current_score,
        tier=tier,
        terminated=False,
    )


# ---------------------------------------------------------------------------
# Alert construction
# ---------------------------------------------------------------------------


class TestAlertConstruction:
    def test_frozen_dataclass(self) -> None:
        alert = Alert(
            alert_id="abc",
            timestamp=1.0,
            rule_id="test",
            severity="high",
            session_id="s1",
            message="msg",
            context=MappingProxyType({}),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            alert.alert_id = "xyz"  # type: ignore[misc]

    def test_all_fields_populated(self) -> None:
        mgr = AlertManager(_cfg())
        fr = _freq(previous_score=0.0, current_score=20.0, tier="tier1")
        alerts = mgr.evaluate(_result(), "s1", fr)
        assert len(alerts) >= 1
        a = alerts[0]
        assert a.alert_id
        assert a.timestamp > 0
        assert a.rule_id
        assert a.severity
        assert a.message
        assert isinstance(a.context, MappingProxyType)


# ---------------------------------------------------------------------------
# Rule: tier_escalation
# ---------------------------------------------------------------------------


class TestTierEscalation:
    def test_none_to_tier1_fires_warning(self) -> None:
        mgr = AlertManager(_cfg())
        fr = _freq(previous_score=0.0, current_score=20.0, tier="tier1")
        alerts = mgr.evaluate(_result(), "s1", fr)
        tier_alerts = [a for a in alerts if a.rule_id == "tier_escalation"]
        assert len(tier_alerts) == 1
        assert tier_alerts[0].severity == "warning"

    def test_tier1_to_tier2_fires_high(self) -> None:
        mgr = AlertManager(_cfg())
        fr = _freq(previous_score=20.0, current_score=35.0, tier="tier2")
        alerts = mgr.evaluate(_result(), "s1", fr)
        tier_alerts = [a for a in alerts if a.rule_id == "tier_escalation"]
        assert len(tier_alerts) == 1
        assert tier_alerts[0].severity == "high"

    def test_tier2_to_tier3_fires_critical(self) -> None:
        mgr = AlertManager(_cfg())
        fr = _freq(previous_score=35.0, current_score=55.0, tier="tier3")
        alerts = mgr.evaluate(_result(), "s1", fr)
        tier_alerts = [a for a in alerts if a.rule_id == "tier_escalation"]
        assert len(tier_alerts) == 1
        assert tier_alerts[0].severity == "critical"

    def test_same_tier_does_not_fire(self) -> None:
        mgr = AlertManager(_cfg())
        fr = _freq(previous_score=20.0, current_score=22.0, tier="tier1")
        alerts = mgr.evaluate(_result(), "s1", fr)
        tier_alerts = [a for a in alerts if a.rule_id == "tier_escalation"]
        assert len(tier_alerts) == 0

    def test_freq_result_none_does_not_fire(self) -> None:
        mgr = AlertManager(_cfg())
        alerts = mgr.evaluate(_result(), "s1", None)
        tier_alerts = [a for a in alerts if a.rule_id == "tier_escalation"]
        assert len(tier_alerts) == 0

    def test_decay_re_entry_fires(self) -> None:
        mgr = AlertManager(_cfg(alert_cooldown_seconds=0.001))
        fr = _freq(previous_score=10.0, current_score=20.0, tier="tier1")
        alerts = mgr.evaluate(_result(), "s1", fr)
        tier_alerts = [a for a in alerts if a.rule_id == "tier_escalation"]
        assert len(tier_alerts) == 1
        assert tier_alerts[0].severity == "warning"

    def test_stable_tier1_no_decay_does_not_fire(self) -> None:
        mgr = AlertManager(_cfg())
        fr = _freq(previous_score=16.0, current_score=18.0, tier="tier1")
        alerts = mgr.evaluate(_result(), "s1", fr)
        tier_alerts = [a for a in alerts if a.rule_id == "tier_escalation"]
        assert len(tier_alerts) == 0


# ---------------------------------------------------------------------------
# Rule: high_severity_finding
# ---------------------------------------------------------------------------


class TestHighSeverityFinding:
    def test_high_finding_fires(self) -> None:
        mgr = AlertManager(_cfg())
        r = _result(findings=(_finding(severity=Severity.HIGH),))
        alerts = mgr.evaluate(r, "s1", None)
        hsf = [a for a in alerts if a.rule_id == "high_severity_finding"]
        assert len(hsf) == 1

    def test_medium_finding_does_not_fire_default(self) -> None:
        mgr = AlertManager(_cfg())
        r = _result(findings=(_finding(severity=Severity.MEDIUM),))
        alerts = mgr.evaluate(r, "s1", None)
        hsf = [a for a in alerts if a.rule_id == "high_severity_finding"]
        assert len(hsf) == 0

    def test_critical_finding_fires(self) -> None:
        mgr = AlertManager(_cfg())
        r = _result(findings=(_finding(severity=Severity.CRITICAL),))
        alerts = mgr.evaluate(r, "s1", None)
        hsf = [a for a in alerts if a.rule_id == "high_severity_finding"]
        assert len(hsf) == 1

    def test_configurable_threshold_medium(self) -> None:
        mgr = AlertManager(_cfg(alert_high_severity_threshold="medium"))
        r = _result(findings=(_finding(severity=Severity.MEDIUM),))
        alerts = mgr.evaluate(r, "s1", None)
        hsf = [a for a in alerts if a.rule_id == "high_severity_finding"]
        assert len(hsf) == 1


# ---------------------------------------------------------------------------
# Rule: rapid_fire
# ---------------------------------------------------------------------------


class TestRapidFire:
    def test_below_threshold_does_not_fire(self) -> None:
        mgr = AlertManager(_cfg(alert_rapid_fire_count=5))
        for _ in range(4):
            alerts = mgr.evaluate(_result(), "s1", None)
        rf = [a for a in alerts if a.rule_id == "rapid_fire"]
        assert len(rf) == 0

    def test_at_threshold_fires(self) -> None:
        mgr = AlertManager(_cfg(alert_rapid_fire_count=5, alert_cooldown_seconds=0.001))
        all_alerts: list[Alert] = []
        for _ in range(5):
            alerts = mgr.evaluate(_result(), "s1", None)
            all_alerts.extend(alerts)
        rf = [a for a in all_alerts if a.rule_id == "rapid_fire"]
        assert len(rf) == 1

    def test_session_scoped_no_cross_contamination(self) -> None:
        mgr = AlertManager(_cfg(alert_rapid_fire_count=3, alert_cooldown_seconds=0.001))
        for _ in range(2):
            mgr.evaluate(_result(), "s1", None)
        for _ in range(2):
            mgr.evaluate(_result(), "s2", None)
        s1_alerts = mgr.evaluate(_result(), "s1", None)
        rf = [a for a in s1_alerts if a.rule_id == "rapid_fire"]
        assert len(rf) == 1

    def test_skipped_when_session_none(self) -> None:
        mgr = AlertManager(_cfg(alert_rapid_fire_count=1))
        alerts = mgr.evaluate(_result(), None, None)
        rf = [a for a in alerts if a.rule_id == "rapid_fire"]
        assert len(rf) == 0

    def test_outside_window_does_not_fire(self) -> None:
        mgr = AlertManager(
            _cfg(
                alert_rapid_fire_count=3,
                alert_rapid_fire_window_seconds=1.0,
            )
        )
        base = time.monotonic()
        with patch("petasos.premium.alerting.time") as mock_time:
            mock_time.time.return_value = base
            for i in range(3):
                mock_time.monotonic.return_value = base + i * 2.0
                alerts = mgr.evaluate(_result(), "s1", None)
        rf = [a for a in alerts if a.rule_id == "rapid_fire"]
        assert len(rf) == 0


# ---------------------------------------------------------------------------
# Rule: cross_session_burst
# ---------------------------------------------------------------------------


class TestCrossSessionBurst:
    def test_below_threshold_does_not_fire(self) -> None:
        mgr = AlertManager(_cfg(alert_cross_session_burst_count=3))
        r = _result(findings=(_finding(),))
        mgr.evaluate(r, "s1", None)
        alerts = mgr.evaluate(r, "s2", None)
        csb = [a for a in alerts if a.rule_id == "cross_session_burst"]
        assert len(csb) == 0

    def test_at_threshold_fires(self) -> None:
        mgr = AlertManager(
            _cfg(
                alert_cross_session_burst_count=3,
                alert_cooldown_seconds=0.001,
            )
        )
        r = _result(findings=(_finding(),))
        mgr.evaluate(r, "s1", None)
        mgr.evaluate(r, "s2", None)
        alerts = mgr.evaluate(r, "s3", None)
        csb = [a for a in alerts if a.rule_id == "cross_session_burst"]
        assert len(csb) == 1
        assert csb[0].severity == "high"

    def test_duplicate_sessions_count_as_one(self) -> None:
        mgr = AlertManager(_cfg(alert_cross_session_burst_count=3))
        r = _result(findings=(_finding(),))
        mgr.evaluate(r, "s1", None)
        mgr.evaluate(r, "s1", None)
        alerts = mgr.evaluate(r, "s2", None)
        csb = [a for a in alerts if a.rule_id == "cross_session_burst"]
        assert len(csb) == 0

    def test_none_session_excluded(self) -> None:
        mgr = AlertManager(_cfg(alert_cross_session_burst_count=2))
        r = _result(findings=(_finding(),))
        mgr.evaluate(r, None, None)
        mgr.evaluate(r, None, None)
        alerts = mgr.evaluate(r, "s1", None)
        csb = [a for a in alerts if a.rule_id == "cross_session_burst"]
        assert len(csb) == 0


# ---------------------------------------------------------------------------
# Rule: pii_volume_spike
# ---------------------------------------------------------------------------


class TestPiiVolumeSpike:
    def test_below_threshold_does_not_fire(self) -> None:
        mgr = AlertManager(_cfg(alert_pii_volume_threshold=5))
        findings = tuple(_finding(finding_type="pii") for _ in range(4))
        r = _result(findings=findings)
        alerts = mgr.evaluate(r, "s1", None)
        pvs = [a for a in alerts if a.rule_id == "pii_volume_spike"]
        assert len(pvs) == 0

    def test_at_threshold_fires(self) -> None:
        mgr = AlertManager(
            _cfg(
                alert_pii_volume_threshold=5,
                alert_cooldown_seconds=0.001,
            )
        )
        findings = tuple(_finding(finding_type="pii") for _ in range(5))
        r = _result(findings=findings)
        alerts = mgr.evaluate(r, "s1", None)
        pvs = [a for a in alerts if a.rule_id == "pii_volume_spike"]
        assert len(pvs) == 1
        assert pvs[0].severity == "warning"

    def test_window_expiry(self) -> None:
        mgr = AlertManager(
            _cfg(
                alert_pii_volume_threshold=3,
                alert_pii_volume_window_seconds=1.0,
            )
        )
        findings = tuple(_finding(finding_type="pii") for _ in range(2))
        r = _result(findings=findings)

        base = time.monotonic()
        with patch("petasos.premium.alerting.time") as mock_time:
            mock_time.time.return_value = 1000.0
            mock_time.monotonic.return_value = base
            mgr.evaluate(r, "s1", None)

            mock_time.monotonic.return_value = base + 2.0
            alerts = mgr.evaluate(r, "s1", None)

        pvs = [a for a in alerts if a.rule_id == "pii_volume_spike"]
        assert len(pvs) == 0


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    def test_cooldown_suppresses_same_key(self) -> None:
        mgr = AlertManager(_cfg(alert_cooldown_seconds=60.0))
        r = _result(findings=(_finding(severity=Severity.HIGH),))
        alerts1 = mgr.evaluate(r, "s1", None)
        alerts2 = mgr.evaluate(r, "s1", None)
        hsf1 = [a for a in alerts1 if a.rule_id == "high_severity_finding"]
        hsf2 = [a for a in alerts2 if a.rule_id == "high_severity_finding"]
        assert len(hsf1) == 1
        assert len(hsf2) == 0
        assert mgr.suppressed_count >= 1

    def test_per_minute_cap(self) -> None:
        mgr = AlertManager(
            _cfg(
                alert_per_minute_cap=2,
                alert_cooldown_seconds=0.001,
            )
        )
        r = _result(findings=(_finding(severity=Severity.HIGH),))
        all_hsf: list[Alert] = []
        for i in range(5):
            alerts = mgr.evaluate(r, f"s{i}", None)
            all_hsf.extend(a for a in alerts if a.rule_id == "high_severity_finding")
        assert len(all_hsf) == 2
        assert mgr.rate_limited_count >= 3

    def test_per_hour_cap(self) -> None:
        mgr = AlertManager(
            _cfg(
                alert_per_hour_cap=2,
                alert_per_minute_cap=100,
                alert_cooldown_seconds=0.001,
            )
        )
        r = _result(findings=(_finding(severity=Severity.HIGH),))
        all_hsf: list[Alert] = []
        for i in range(5):
            alerts = mgr.evaluate(r, f"s{i}", None)
            all_hsf.extend(a for a in alerts if a.rule_id == "high_severity_finding")
        assert len(all_hsf) == 2
        assert mgr.rate_limited_count >= 3

    def test_100_rapid_triggers_bounded(self) -> None:
        mgr = AlertManager(
            _cfg(
                alert_per_minute_cap=5,
                alert_cooldown_seconds=0.001,
            )
        )
        r = _result(findings=(_finding(severity=Severity.HIGH),))
        total_fired = 0
        for i in range(100):
            alerts = mgr.evaluate(r, f"s{i}", None)
            total_fired += len([a for a in alerts if a.rule_id == "high_severity_finding"])
        assert total_fired <= 5

    def test_suppressed_and_rate_limited_counts(self) -> None:
        mgr = AlertManager(_cfg(alert_cooldown_seconds=60.0))
        r = _result(findings=(_finding(severity=Severity.HIGH),))
        mgr.evaluate(r, "s1", None)
        mgr.evaluate(r, "s1", None)
        assert mgr.suppressed_count >= 1


# ---------------------------------------------------------------------------
# Critical exemption
# ---------------------------------------------------------------------------


class TestCriticalExemption:
    def test_tier3_bypasses_cooldown(self) -> None:
        mgr = AlertManager(_cfg(alert_cooldown_seconds=9999.0))
        fr = _freq(previous_score=35.0, current_score=55.0, tier="tier3")
        alerts1 = mgr.evaluate(_result(), "s1", fr)
        alerts2 = mgr.evaluate(_result(), "s1", fr)
        t1 = [a for a in alerts1 if a.rule_id == "tier_escalation" and a.severity == "critical"]
        t2 = [a for a in alerts2 if a.rule_id == "tier_escalation" and a.severity == "critical"]
        assert len(t1) == 1
        assert len(t2) == 1

    def test_tier3_bypasses_per_minute_cap(self) -> None:
        mgr = AlertManager(_cfg(alert_per_minute_cap=1, alert_per_session_contribution_cap=1))
        fr = _freq(previous_score=35.0, current_score=55.0, tier="tier3")
        all_critical: list[Alert] = []
        for _ in range(5):
            alerts = mgr.evaluate(_result(), "s1", fr)
            all_critical.extend(
                a for a in alerts if a.rule_id == "tier_escalation" and a.severity == "critical"
            )
        assert len(all_critical) == 5

    def test_tier3_bypasses_per_hour_cap(self) -> None:
        mgr = AlertManager(_cfg(alert_per_hour_cap=1))
        fr = _freq(previous_score=35.0, current_score=55.0, tier="tier3")
        all_critical: list[Alert] = []
        for _ in range(3):
            alerts = mgr.evaluate(_result(), "s1", fr)
            all_critical.extend(
                a for a in alerts if a.rule_id == "tier_escalation" and a.severity == "critical"
            )
        assert len(all_critical) == 3

    def test_non_critical_still_rate_limited(self) -> None:
        mgr = AlertManager(_cfg(alert_cooldown_seconds=60.0))
        r = _result(findings=(_finding(severity=Severity.HIGH),))
        fr = _freq(previous_score=35.0, current_score=55.0, tier="tier3")
        alerts1 = mgr.evaluate(r, "s1", fr)
        alerts2 = mgr.evaluate(r, "s1", fr)
        hsf1 = [a for a in alerts1 if a.rule_id == "high_severity_finding"]
        hsf2 = [a for a in alerts2 if a.rule_id == "high_severity_finding"]
        assert len(hsf1) == 1
        assert len(hsf2) == 0


# ---------------------------------------------------------------------------
# Critical cap (PET-16)
# ---------------------------------------------------------------------------


class TestCriticalCap:
    def test_critical_cap_bounds_fanout(self) -> None:
        mgr = AlertManager(_cfg(alert_critical_per_minute_cap=5))
        fr = _freq(previous_score=35.0, current_score=55.0, tier="tier3")
        all_critical: list[Alert] = []
        for i in range(100):
            alerts = mgr.evaluate(_result(), f"s{i}", fr)
            all_critical.extend(
                a for a in alerts if a.rule_id == "tier_escalation" and a.severity == "critical"
            )
        assert len(all_critical) <= 5

    def test_critical_cap_default_allows_legitimate_burst(self) -> None:
        mgr = AlertManager(_cfg())
        fr = _freq(previous_score=35.0, current_score=55.0, tier="tier3")
        all_critical: list[Alert] = []
        for i in range(10):
            alerts = mgr.evaluate(_result(), f"s{i}", fr)
            all_critical.extend(
                a for a in alerts if a.rule_id == "tier_escalation" and a.severity == "critical"
            )
        assert len(all_critical) == 10

    def test_critical_cap_per_rule_id_isolation(self) -> None:
        mgr = AlertManager(_cfg(alert_critical_per_minute_cap=1))
        fr = _freq(previous_score=35.0, current_score=55.0, tier="tier3")
        alerts1 = mgr.evaluate(_result(), "s1", fr)
        t1 = [a for a in alerts1 if a.rule_id == "tier_escalation" and a.severity == "critical"]
        assert len(t1) == 1
        alerts2 = mgr.evaluate(_result(), "s2", fr)
        t2 = [a for a in alerts2 if a.rule_id == "tier_escalation" and a.severity == "critical"]
        assert len(t2) == 0
        assert "tier_escalation" in mgr._critical_per_minute_timestamps
        assert mgr._critical_per_minute_timestamps.get("other_rule") is None

    def test_critical_cap_resets_after_window(self) -> None:
        base = time.monotonic()
        mgr = AlertManager(_cfg(alert_critical_per_minute_cap=2))
        fr = _freq(previous_score=35.0, current_score=55.0, tier="tier3")

        with patch("petasos.premium.alerting.time") as mock_time:
            mock_time.time.return_value = 1000.0

            mock_time.monotonic.return_value = base
            mgr.evaluate(_result(), "s1", fr)
            mgr.evaluate(_result(), "s2", fr)

            mock_time.monotonic.return_value = base + 0.5
            alerts_capped = mgr.evaluate(_result(), "s3", fr)
            capped = [
                a
                for a in alerts_capped
                if a.rule_id == "tier_escalation" and a.severity == "critical"
            ]
            assert len(capped) == 0

            mock_time.monotonic.return_value = base + 61.0
            alerts_after = mgr.evaluate(_result(), "s4", fr)
            after = [
                a
                for a in alerts_after
                if a.rule_id == "tier_escalation" and a.severity == "critical"
            ]
            assert len(after) == 1

    def test_tier3_bypasses_noncritical_caps(self) -> None:
        mgr = AlertManager(
            _cfg(
                alert_per_minute_cap=1,
                alert_per_session_contribution_cap=1,
                alert_per_hour_cap=1,
                alert_cooldown_seconds=9999.0,
            )
        )
        fr = _freq(previous_score=35.0, current_score=55.0, tier="tier3")
        all_critical: list[Alert] = []
        for _ in range(3):
            alerts = mgr.evaluate(_result(), "s1", fr)
            all_critical.extend(
                a for a in alerts if a.rule_id == "tier_escalation" and a.severity == "critical"
            )
        assert len(all_critical) == 3

    def test_critical_fanout_callback_bounded(self) -> None:
        received: list[Alert] = []
        mgr = AlertManager(
            _cfg(alert_critical_per_minute_cap=10),
            on_alert=received.append,
        )
        fr = _freq(previous_score=35.0, current_score=55.0, tier="tier3")
        for i in range(200):
            mgr.evaluate(_result(), f"s{i}", fr)
        critical_callbacks = [
            a for a in received if a.rule_id == "tier_escalation" and a.severity == "critical"
        ]
        assert len(critical_callbacks) <= 10


# ---------------------------------------------------------------------------
# Ring buffer
# ---------------------------------------------------------------------------


class TestRingBuffer:
    def test_buffer_respects_maxlen(self) -> None:
        mgr = AlertManager(_cfg(alert_ring_buffer_capacity=5, alert_rapid_fire_count=5))
        for _ in range(10):
            mgr.evaluate(_result(), "s1", None)
        buf = mgr._ring_buffers.get("rapid_fire|s1")
        assert buf is not None
        assert len(buf) == 5

    def test_buffer_entries_correct_shape(self) -> None:
        mgr = AlertManager(_cfg())
        r = _result(findings=(_finding(),))
        mgr.evaluate(r, "s1", None)
        buf = mgr._ring_buffers.get("cross_session_burst")
        assert buf is not None
        ts, sid = buf[0]
        assert isinstance(ts, float)
        assert sid == "s1"


# ---------------------------------------------------------------------------
# Callback behavior
# ---------------------------------------------------------------------------


class TestAlertCallbackBehavior:
    def test_no_callback_returns_alerts(self) -> None:
        mgr = AlertManager(_cfg(), on_alert=None)
        r = _result(findings=(_finding(severity=Severity.HIGH),))
        alerts = mgr.evaluate(r, "s1", None)
        assert len(alerts) >= 1

    def test_callback_receives_each_alert(self) -> None:
        received: list[Alert] = []
        mgr = AlertManager(_cfg(), on_alert=received.append)
        r = _result(findings=(_finding(severity=Severity.HIGH),))
        alerts = mgr.evaluate(r, "s1", None)
        assert len(received) == len(alerts)

    def test_callback_exception_swallowed(self) -> None:
        def bad_cb(a: Alert) -> None:
            raise ValueError("boom")

        mgr = AlertManager(_cfg(), on_alert=bad_cb)
        r = _result(findings=(_finding(severity=Severity.HIGH),))
        alerts = mgr.evaluate(r, "s1", None)
        assert len(alerts) >= 1
        assert len(mgr.callback_errors) >= 1
        assert "ValueError" in mgr.callback_errors[0]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestAlertStats:
    def test_alert_count_reflects_fired(self) -> None:
        mgr = AlertManager(_cfg(alert_cooldown_seconds=0.001))
        r = _result(findings=(_finding(severity=Severity.HIGH),))
        mgr.evaluate(r, "s1", None)
        mgr.evaluate(r, "s2", None)
        assert mgr.alert_count >= 2

    def test_suppressed_count_reflects_dedup(self) -> None:
        mgr = AlertManager(_cfg(alert_cooldown_seconds=60.0))
        r = _result(findings=(_finding(severity=Severity.HIGH),))
        mgr.evaluate(r, "s1", None)
        mgr.evaluate(r, "s1", None)
        assert mgr.suppressed_count >= 1

    def test_rate_limited_count_reflects_caps(self) -> None:
        mgr = AlertManager(
            _cfg(
                alert_per_minute_cap=1,
                alert_per_session_contribution_cap=1,
                alert_cooldown_seconds=0.001,
            )
        )
        r = _result(findings=(_finding(severity=Severity.HIGH),))
        mgr.evaluate(r, "s1", None)
        mgr.evaluate(r, "s2", None)
        mgr.evaluate(r, "s3", None)
        assert mgr.rate_limited_count >= 2


# ---------------------------------------------------------------------------
# Session contribution cap (PET-17)
# ---------------------------------------------------------------------------


class TestSessionContributionCap:
    def test_session_contribution_cap_limits_single_session(self) -> None:
        base = time.monotonic()
        with patch("petasos.premium.alerting.time") as mock_time:
            mock_time.time.return_value = 1000.0
            mgr = AlertManager(
                _cfg(
                    alert_per_minute_cap=10,
                    alert_per_session_contribution_cap=2,
                    alert_cooldown_seconds=0.001,
                )
            )
            r = _result(findings=(_finding(severity=Severity.HIGH),))
            all_hsf: list[Alert] = []
            for i in range(10):
                mock_time.monotonic.return_value = base + i * 0.01
                alerts = mgr.evaluate(r, "s1", None)
                all_hsf.extend(a for a in alerts if a.rule_id == "high_severity_finding")
            assert len(all_hsf) <= 2
            assert mgr.session_rate_limited_count >= 1

    def test_throwaway_sessions_cannot_exhaust_rule_cap(self) -> None:
        base = time.monotonic()
        with patch("petasos.premium.alerting.time") as mock_time:
            mock_time.time.return_value = 1000.0
            mock_time.monotonic.return_value = base

            mgr = AlertManager(
                _cfg(
                    alert_per_minute_cap=10,
                    alert_per_session_contribution_cap=1,
                    alert_cooldown_seconds=0.001,
                )
            )
            r = _result(findings=(_finding(severity=Severity.HIGH),))
            for i in range(100):
                mgr.evaluate(r, f"throwaway-{i}", None)

            mock_time.monotonic.return_value = base + 61.0
            alerts = mgr.evaluate(r, "legit-session", None)
            hsf = [a for a in alerts if a.rule_id == "high_severity_finding"]
            assert len(hsf) == 1

    def test_session_contribution_independent_across_rules(self) -> None:
        base = time.monotonic()
        with patch("petasos.premium.alerting.time") as mock_time:
            mock_time.time.return_value = 1000.0
            mgr = AlertManager(
                _cfg(
                    alert_per_minute_cap=10,
                    alert_per_session_contribution_cap=1,
                    alert_cooldown_seconds=0.001,
                    alert_rapid_fire_count=3,
                )
            )
            r = _result(findings=(_finding(severity=Severity.HIGH),))
            mock_time.monotonic.return_value = base
            a1 = mgr.evaluate(r, "s1", None)
            assert len([a for a in a1 if a.rule_id == "high_severity_finding"]) == 1
            assert len([a for a in a1 if a.rule_id == "rapid_fire"]) == 0

            mock_time.monotonic.return_value = base + 0.01
            a2 = mgr.evaluate(r, "s1", None)
            assert len([a for a in a2 if a.rule_id == "high_severity_finding"]) == 0

            mock_time.monotonic.return_value = base + 0.02
            a3 = mgr.evaluate(r, "s1", None)
            rf = [a for a in a3 if a.rule_id == "rapid_fire"]
            assert len(rf) == 1

    def test_session_contribution_window_resets(self) -> None:
        base = time.monotonic()
        with patch("petasos.premium.alerting.time") as mock_time:
            mock_time.time.return_value = 1000.0

            mgr = AlertManager(
                _cfg(
                    alert_per_minute_cap=10,
                    alert_per_session_contribution_cap=1,
                    alert_cooldown_seconds=0.001,
                )
            )
            r = _result(findings=(_finding(severity=Severity.HIGH),))

            mock_time.monotonic.return_value = base
            mgr.evaluate(r, "s1", None)
            alerts_blocked = mgr.evaluate(r, "s1", None)
            hsf_blocked = [a for a in alerts_blocked if a.rule_id == "high_severity_finding"]
            assert len(hsf_blocked) == 0

            mock_time.monotonic.return_value = base + 61.0
            alerts_after = mgr.evaluate(r, "s1", None)
            hsf_after = [a for a in alerts_after if a.rule_id == "high_severity_finding"]
            assert len(hsf_after) == 1

    def test_session_none_uses_none_key(self) -> None:
        base = time.monotonic()
        with patch("petasos.premium.alerting.time") as mock_time:
            mock_time.time.return_value = 1000.0
            mgr = AlertManager(
                _cfg(
                    alert_per_minute_cap=10,
                    alert_per_session_contribution_cap=1,
                    alert_cooldown_seconds=0.001,
                )
            )
            r = _result(findings=(_finding(severity=Severity.HIGH),))
            mock_time.monotonic.return_value = base
            mgr.evaluate(r, None, None)
            mock_time.monotonic.return_value = base + 0.01
            alerts = mgr.evaluate(r, None, None)
            hsf = [a for a in alerts if a.rule_id == "high_severity_finding"]
            assert len(hsf) == 0
            assert mgr.session_rate_limited_count >= 1

    def test_per_session_deque_pruned(self) -> None:
        base = time.monotonic()
        with patch("petasos.premium.alerting.time") as mock_time:
            mock_time.time.return_value = 1000.0
            mock_time.monotonic.return_value = base

            mgr = AlertManager(
                _cfg(
                    alert_per_minute_cap=10,
                    alert_per_session_contribution_cap=2,
                    alert_cooldown_seconds=0.001,
                )
            )
            r = _result(findings=(_finding(severity=Severity.HIGH),))
            mgr.evaluate(r, "s1", None)
            assert len(mgr._per_session_minute_timestamps) >= 1

            mock_time.monotonic.return_value = base + 61.0
            mgr.evaluate(r, "s2", None)
            assert ("high_severity_finding", "s1") not in mgr._per_session_minute_timestamps

    def test_memory_bound_rejects_new_sessions(self) -> None:
        mgr = AlertManager(
            _cfg(
                alert_per_minute_cap=500,
                alert_per_hour_cap=500,
                alert_per_session_contribution_cap=2,
                alert_cooldown_seconds=0.001,
                alert_max_session_contribution_entries=100,
            )
        )
        r = _result(findings=(_finding(severity=Severity.HIGH),))
        for i in range(200):
            mgr.evaluate(r, f"s{i}", None)
        mgr.evaluate(_result(), "trigger-prune", None)
        assert len(mgr._per_session_minute_timestamps) <= 105
        assert mgr.session_rate_limited_count >= 1

    def test_cap_1_suppresses_reentry(self) -> None:
        base = time.monotonic()
        with patch("petasos.premium.alerting.time") as mock_time:
            mock_time.time.return_value = 1000.0
            mock_time.monotonic.return_value = base

            mgr = AlertManager(
                _cfg(
                    alert_per_minute_cap=10,
                    alert_per_session_contribution_cap=1,
                    alert_cooldown_seconds=0.001,
                )
            )
            r = _result(findings=(_finding(severity=Severity.HIGH),))
            alerts1 = mgr.evaluate(r, "s1", None)
            assert len([a for a in alerts1 if a.rule_id == "high_severity_finding"]) == 1

            mock_time.monotonic.return_value = base + 30.0
            alerts2 = mgr.evaluate(r, "s1", None)
            assert len([a for a in alerts2 if a.rule_id == "high_severity_finding"]) == 0
            assert mgr.session_rate_limited_count >= 1

    def test_three_gate_composition(self) -> None:
        base = time.monotonic()
        with patch("petasos.premium.alerting.time") as mock_time:
            mock_time.time.return_value = 1000.0

            mgr = AlertManager(
                _cfg(
                    alert_cooldown_seconds=10.0,
                    alert_per_session_contribution_cap=2,
                    alert_per_minute_cap=5,
                )
            )
            r = _result(findings=(_finding(severity=Severity.HIGH),))

            mock_time.monotonic.return_value = base
            a1 = mgr.evaluate(r, "s1", None)
            assert len([a for a in a1 if a.rule_id == "high_severity_finding"]) == 1

            mock_time.monotonic.return_value = base + 5.0
            a2 = mgr.evaluate(r, "s1", None)
            assert len([a for a in a2 if a.rule_id == "high_severity_finding"]) == 0
            assert mgr.suppressed_count >= 1

            mock_time.monotonic.return_value = base + 11.0
            a3 = mgr.evaluate(r, "s1", None)
            assert len([a for a in a3 if a.rule_id == "high_severity_finding"]) == 1

            mock_time.monotonic.return_value = base + 22.0
            a4 = mgr.evaluate(r, "s1", None)
            assert len([a for a in a4 if a.rule_id == "high_severity_finding"]) == 0
            assert mgr.session_rate_limited_count >= 1

    def test_session_rate_limited_count_separate(self) -> None:
        base = time.monotonic()
        with patch("petasos.premium.alerting.time") as mock_time:
            mock_time.time.return_value = 1000.0
            mgr = AlertManager(
                _cfg(
                    alert_per_minute_cap=10,
                    alert_per_session_contribution_cap=1,
                    alert_cooldown_seconds=0.001,
                )
            )
            r = _result(findings=(_finding(severity=Severity.HIGH),))
            mock_time.monotonic.return_value = base
            mgr.evaluate(r, "s1", None)
            mock_time.monotonic.return_value = base + 0.01
            mgr.evaluate(r, "s1", None)
            assert mgr.session_rate_limited_count >= 1
            assert mgr.rate_limited_count == 0

    def test_cross_field_validation_cap_gt_per_minute(self) -> None:
        with pytest.raises(ValueError, match="must be <= alert_per_minute_cap"):
            _cfg(alert_per_session_contribution_cap=10, alert_per_minute_cap=5)
        _cfg(alert_per_session_contribution_cap=5, alert_per_minute_cap=5)

    def test_memory_bound_recovery_after_expiry(self) -> None:
        base = time.monotonic()
        with patch("petasos.premium.alerting.time") as mock_time:
            mock_time.time.return_value = 1000.0
            mock_time.monotonic.return_value = base

            mgr = AlertManager(
                _cfg(
                    alert_per_minute_cap=500,
                    alert_per_hour_cap=500,
                    alert_per_session_contribution_cap=2,
                    alert_cooldown_seconds=0.001,
                    alert_max_session_contribution_entries=50,
                )
            )
            r = _result(findings=(_finding(severity=Severity.HIGH),))
            for i in range(100):
                mgr.evaluate(r, f"s{i}", None)
            assert mgr.session_rate_limited_count >= 1

            mock_time.monotonic.return_value = base + 61.0
            alerts = mgr.evaluate(r, "fresh-session", None)
            hsf = [a for a in alerts if a.rule_id == "high_severity_finding"]
            assert len(hsf) == 1
