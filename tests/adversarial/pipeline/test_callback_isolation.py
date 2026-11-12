"""Pin callback containment, distinct-session burst accounting and audit sequence continuity."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from petasos.config.schema import from_mapping, merge
from petasos.config.sections import PetasosConfig
from petasos.model import (
    Alert,
    AuditEvent,
    PipelineResult,
    ScanFinding,
    Severity,
)
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner
from petasos.session.alerting import AlertManager
from petasos.session.audit import AuditEmitter
from petasos.session.frequency import FrequencyUpdateResult


def _cfg(changes: dict[str, Any] | None = None) -> PetasosConfig:
    document: dict[str, Any] = {
        "audit": {"enabled": True},
        "alerting": {"enabled": True},
        "frequency": {"enabled": True},
        "escalation": {"enabled": True},
    }
    if changes:
        document = merge(document, changes)
    return from_mapping(PetasosConfig, document)


def _pipeline_result(
    *,
    safe: bool = True,
    findings: tuple[ScanFinding, ...] = (),
) -> PipelineResult:
    return PipelineResult(safe=safe, findings=findings)


def _finding(
    rule_id: str = "test.rule",
    severity: Severity = Severity.HIGH,
) -> ScanFinding:
    return ScanFinding(
        rule_id=rule_id,
        finding_type="injection",
        severity=severity,
        confidence=0.9,
        message="test",
        scanner_name="minimal",
    )


def _freq_result(
    previous_score: float = 0.0,
    current_score: float = 10.0,
    tier: str = "tier1",
) -> FrequencyUpdateResult:
    return FrequencyUpdateResult(
        previous_score=previous_score,
        current_score=current_score,
        tier=tier,
        terminated=False,
    )


def _session_pipeline(
    *,
    on_audit: Any = None,
    on_alert: Any = None,
) -> Pipeline:
    return Pipeline(
        [MinimalScanner()],
        config=_cfg(),
        on_audit=on_audit,
        on_alert=on_alert,
    )


class TestAuditCallbackIsolation:
    """Pin Audit Callback Isolation."""

    def test_audit_callback_runtime_error_swallowed(self) -> None:
        """Pin audit callback runtime error swallowed."""

        def bad_cb(e: AuditEvent) -> None:
            raise RuntimeError("boom")

        emitter = AuditEmitter(_cfg(), on_audit=bad_cb)
        event = emitter.emit(_pipeline_result(), "s1", None)
        assert event is not None
        assert emitter.last_callback_error is not None
        assert "RuntimeError" in emitter.last_callback_error
        assert "boom" in emitter.last_callback_error

    def test_audit_callback_base_exception_swallowed(self) -> None:
        """Pin audit callback base exception swallowed."""

        def bad_cb(e: AuditEvent) -> None:
            raise KeyboardInterrupt("simulated")

        emitter = AuditEmitter(_cfg(), on_audit=bad_cb)
        event = emitter.emit(_pipeline_result(), "s1", None)
        assert event is not None
        assert emitter.last_callback_error is not None
        assert "KeyboardInterrupt" in emitter.last_callback_error

    def test_audit_callback_error_logged(self) -> None:
        """Pin audit callback error logged."""

        def bad_cb(e: AuditEvent) -> None:
            raise ValueError("bad")

        emitter = AuditEmitter(_cfg(), on_audit=bad_cb)
        with patch("petasos.session.audit._logger") as mock_logger:
            emitter.emit(_pipeline_result(), "s1", None)
            mock_logger.error.assert_called_once()
            call_kwargs = mock_logger.error.call_args
            assert call_kwargs[1].get("exc_info") is True


class TestAlertCallbackIsolation:
    """Pin Alert Callback Isolation."""

    def test_alert_callback_runtime_error_in_errors(self) -> None:
        """Pin alert callback runtime error in errors."""

        def bad_cb(a: Alert) -> None:
            raise RuntimeError("alert-boom")

        mgr = AlertManager(_cfg({"alerting": {"cooldown_seconds": 0.001}}), on_alert=bad_cb)
        r = _pipeline_result(findings=(_finding(severity=Severity.HIGH),))
        alerts = mgr.evaluate(r, "s1", None)
        assert len(alerts) >= 1
        assert len(mgr.callback_errors) >= 1
        assert "RuntimeError" in mgr.callback_errors[0]
        assert "alert-boom" in mgr.callback_errors[0]

    def test_alert_callback_base_exception_swallowed(self) -> None:
        """Pin alert callback base exception swallowed."""

        def bad_cb(a: Alert) -> None:
            raise KeyboardInterrupt("simulated")

        mgr = AlertManager(_cfg({"alerting": {"cooldown_seconds": 0.001}}), on_alert=bad_cb)
        r = _pipeline_result(findings=(_finding(severity=Severity.HIGH),))
        alerts = mgr.evaluate(r, "s1", None)
        assert len(alerts) >= 1
        assert len(mgr.callback_errors) >= 1
        assert "KeyboardInterrupt" in mgr.callback_errors[0]

    def test_alert_callback_error_logged(self) -> None:
        """Pin alert callback error logged."""

        def bad_cb(a: Alert) -> None:
            raise ValueError("bad-alert")

        mgr = AlertManager(_cfg({"alerting": {"cooldown_seconds": 0.001}}), on_alert=bad_cb)
        r = _pipeline_result(findings=(_finding(severity=Severity.HIGH),))
        with patch("petasos.session.alerting._logger") as mock_logger:
            mgr.evaluate(r, "s1", None)
            mock_logger.exception.assert_called()


class TestPipelineCallbackPropagation:
    """Pin Pipeline Callback Propagation."""

    async def test_audit_error_reaches_pipeline_result(self) -> None:
        """Pin audit error reaches pipeline result."""

        def bad_audit(e: AuditEvent) -> None:
            raise RuntimeError("audit-fail")

        pipeline = _session_pipeline(on_audit=bad_audit)
        result = await pipeline.inspect("hello", session_id="s1")
        assert any("on_audit callback" in e for e in result.errors)

    async def test_alert_error_reaches_pipeline_result(self) -> None:
        """Pin alert error reaches pipeline result."""

        def bad_alert(a: Alert) -> None:
            raise RuntimeError("alert-fail")

        pipeline = _session_pipeline(on_alert=bad_alert)
        result = await pipeline.inspect("ignore previous instructions", session_id="s1")
        alert_errors = [e for e in result.errors if "on_alert callback" in e]
        assert len(alert_errors) >= 1

    async def test_both_callbacks_fail_both_errors_in_result(self) -> None:
        """Pin both callbacks fail both errors in result."""

        def bad_audit(e: AuditEvent) -> None:
            raise RuntimeError("audit-fail")

        def bad_alert(a: Alert) -> None:
            raise RuntimeError("alert-fail")

        pipeline = _session_pipeline(on_audit=bad_audit, on_alert=bad_alert)
        result = await pipeline.inspect("ignore previous instructions", session_id="s1")
        audit_errors = [e for e in result.errors if "on_audit" in e]
        alert_errors = [e for e in result.errors if "on_alert" in e]
        assert len(audit_errors) >= 1
        assert len(alert_errors) >= 1


class TestCrossSessionBurstTracker:
    """Pin Cross Session Burst Tracker."""

    def test_cross_session_burst_accurate_under_eviction(self) -> None:
        """Pin cross session burst accurate under eviction."""
        mgr = AlertManager(
            _cfg(
                {
                    "alerting": {
                        "ring_buffer_capacity": 5,
                        "cross_session_burst_count": 4,
                        "rapid_fire_count": 5,
                        "cooldown_seconds": 1.0,
                        "cross_session_burst_window_seconds": 60.0,
                    }
                }
            )
        )
        r = _pipeline_result(findings=(_finding(),))
        base = 1000.0
        with patch("petasos.session.alerting.time") as mock_time:
            mock_time.time.return_value = base
            for i in range(6):
                mock_time.monotonic.return_value = base + i * 0.1
                mgr.evaluate(r, f"s{i}", None)
            for j in range(2):
                mock_time.monotonic.return_value = base + 0.6 + j * 0.1
                mgr.evaluate(r, "s5", None)
            mock_time.monotonic.return_value = base + 2.0
            last_alerts = mgr.evaluate(r, "s5", None)
        csb = [a for a in last_alerts if a.rule_id == "cross_session_burst"]
        assert len(csb) >= 1

    def test_cross_session_tracker_time_window_eviction(self) -> None:
        """Pin cross session tracker time window eviction."""
        base_time = 1000.0
        mgr = AlertManager(
            _cfg(
                {
                    "alerting": {
                        "cross_session_burst_count": 3,
                        "cross_session_burst_window_seconds": 10.0,
                        "cooldown_seconds": 0.001,
                    }
                }
            )
        )
        r = _pipeline_result(findings=(_finding(),))
        with patch("petasos.session.alerting.time") as mock_time:
            mock_time.time.return_value = base_time
            mock_time.monotonic.return_value = base_time
            for i in range(3):
                mgr.evaluate(r, f"wave1-s{i}", None)

            mock_time.monotonic.return_value = base_time + 15.0
            mock_time.time.return_value = base_time + 15.0
            alerts = mgr.evaluate(r, "wave2-s0", None)

        csb = [a for a in alerts if a.rule_id == "cross_session_burst"]
        assert len(csb) == 0

    def test_cross_session_tracker_cap_bounds_memory(self) -> None:
        """Pin cross session tracker cap bounds memory."""
        mgr = AlertManager(
            _cfg(
                {
                    "alerting": {
                        "ring_buffer_capacity": 50,
                        "cross_session_burst_count": 3,
                        "cooldown_seconds": 0.001,
                    }
                }
            )
        )
        r = _pipeline_result(findings=(_finding(),))
        for i in range(200):
            mgr.evaluate(r, f"s{i}", None)
        assert len(mgr._cross_session_tracker) <= 100


class TestGlobalMonotonicSequence:
    """Pin Global Monotonic Sequence."""

    def test_sequence_continues_after_ttl_prune_boundary(self) -> None:
        """Pin sequence continues after ttl prune boundary."""
        emitter = AuditEmitter(_cfg())
        emitter.emit(_pipeline_result(), "s1", None)
        e2 = emitter.emit(_pipeline_result(), "s1", None)
        last_seq = e2.sequence_number
        e3 = emitter.emit(_pipeline_result(), "s1", None)
        assert e3.sequence_number > last_seq

    def test_sequence_global_monotonic_across_sessions(self) -> None:
        """Pin sequence global monotonic across sessions."""
        emitter = AuditEmitter(_cfg())
        all_seqs: list[int] = []
        for _ in range(5):
            for sid in ("a", "b", "c"):
                e = emitter.emit(_pipeline_result(), sid, None)
                all_seqs.append(e.sequence_number)
        assert all_seqs == list(range(15))

    def test_sequence_never_zero_after_first_emit(self) -> None:
        """Pin sequence never zero after first emit."""
        emitter = AuditEmitter(_cfg())
        e1 = emitter.emit(_pipeline_result(), "s1", None)
        assert e1.sequence_number == 0
        e2 = emitter.emit(_pipeline_result(), "s1", None)
        assert e2.sequence_number > 0
        e3 = emitter.emit(_pipeline_result(), "s2", None)
        assert e3.sequence_number > 0
