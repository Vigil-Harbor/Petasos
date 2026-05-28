from __future__ import annotations

import uuid
from types import MappingProxyType
from unittest.mock import patch

import pytest

from petasos._types import AuditEvent, PipelineResult, ScanFinding, ScanResult, Severity
from petasos.config import PetasosConfig
from petasos.premium.audit import AuditEmitter
from petasos.premium.frequency import FrequencyUpdateResult


def _cfg(**overrides: object) -> PetasosConfig:
    defaults: dict[str, object] = {
        "audit_enabled": True,
        "audit_verbosity": "standard",
    }
    defaults.update(overrides)
    return PetasosConfig(**defaults)  # type: ignore[arg-type]


def _result(
    *,
    safe: bool = True,
    findings: tuple[ScanFinding, ...] = (),
    scanner_results: tuple[ScanResult, ...] = (),
) -> PipelineResult:
    return PipelineResult(
        safe=safe,
        findings=findings,
        scanner_results=scanner_results,
    )


def _finding(
    rule_id: str = "test.rule",
    severity: Severity = Severity.HIGH,
    confidence: float = 0.9,
) -> ScanFinding:
    return ScanFinding(
        rule_id=rule_id,
        finding_type="injection",
        severity=severity,
        confidence=confidence,
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


# ---------------------------------------------------------------------------
# AuditEvent construction
# ---------------------------------------------------------------------------


class TestAuditEventConstruction:
    def test_frozen_dataclass_raises_on_mutation(self) -> None:
        event = AuditEvent(
            event_id="abc",
            timestamp=1.0,
            session_id="s1",
            event_type="scan_complete",
            payload=MappingProxyType({}),
            sequence_number=0,
        )
        with pytest.raises(AttributeError):
            event.event_id = "xyz"  # type: ignore[misc]

    def test_all_fields_populated(self) -> None:
        emitter = AuditEmitter(_cfg())
        event = emitter.emit(_result(), "s1", None)
        assert event.event_id
        assert event.timestamp > 0
        assert event.session_id == "s1"
        assert event.event_type == "scan_complete"
        assert isinstance(event.payload, MappingProxyType)
        assert event.sequence_number == 0

    def test_event_id_is_valid_uuid4_hex(self) -> None:
        emitter = AuditEmitter(_cfg())
        event = emitter.emit(_result(), "s1", None)
        parsed = uuid.UUID(event.event_id)
        assert parsed.version == 4


# ---------------------------------------------------------------------------
# Verbosity levels
# ---------------------------------------------------------------------------


class TestVerbosityLevels:
    def test_minimal_payload_keys(self) -> None:
        emitter = AuditEmitter(_cfg(audit_verbosity="minimal"))
        event = emitter.emit(_result(), "s1", None)
        assert set(event.payload.keys()) == {"safe", "finding_count"}

    def test_standard_payload_keys(self) -> None:
        emitter = AuditEmitter(_cfg(audit_verbosity="standard"))
        fr = _freq_result()
        event = emitter.emit(_result(findings=(_finding(),)), "s1", fr)
        expected = {"safe", "finding_count", "findings", "escalation_tier", "session_score"}
        assert set(event.payload.keys()) == expected

    def test_verbose_payload_keys(self) -> None:
        emitter = AuditEmitter(_cfg(audit_verbosity="verbose"))
        sr = ScanResult(scanner_name="minimal", findings=(), duration_ms=1.0)
        fr = _freq_result()
        event = emitter.emit(_result(scanner_results=(sr,)), "s1", fr)
        expected = {
            "safe",
            "finding_count",
            "findings",
            "escalation_tier",
            "session_score",
            "scanner_results",
            "config_snapshot",
            "timing",
        }
        assert set(event.payload.keys()) == expected

    def test_minimal_no_extra_keys(self) -> None:
        emitter = AuditEmitter(_cfg(audit_verbosity="minimal"))
        fr = _freq_result()
        event = emitter.emit(_result(findings=(_finding(),)), "s1", fr)
        assert "findings" not in event.payload
        assert "scanner_results" not in event.payload

    def test_standard_findings_content(self) -> None:
        f = _finding(rule_id="test.injection", severity=Severity.HIGH, confidence=0.85)
        emitter = AuditEmitter(_cfg(audit_verbosity="standard"))
        event = emitter.emit(_result(findings=(f,)), "s1", _freq_result())
        findings_list = event.payload["findings"]
        assert len(findings_list) == 1
        assert findings_list[0]["rule_id"] == "test.injection"
        assert findings_list[0]["severity"] == "high"
        assert findings_list[0]["confidence"] == 0.85

    def test_verbose_scanner_results_content(self) -> None:
        sr = ScanResult(scanner_name="test_scanner", findings=(), duration_ms=5.5, error="oops")
        emitter = AuditEmitter(_cfg(audit_verbosity="verbose"))
        event = emitter.emit(_result(scanner_results=(sr,)), "s1", _freq_result())
        srs = event.payload["scanner_results"]
        assert len(srs) == 1
        assert srs[0]["scanner_name"] == "test_scanner"
        assert srs[0]["duration_ms"] == 5.5
        assert srs[0]["error"] == "oops"

    def test_verbose_config_snapshot_is_dict(self) -> None:
        emitter = AuditEmitter(_cfg(audit_verbosity="verbose"))
        event = emitter.emit(_result(), "s1", _freq_result())
        assert isinstance(event.payload["config_snapshot"], dict)
        assert "audit_verbosity" in event.payload["config_snapshot"]


# ---------------------------------------------------------------------------
# Sequence numbers
# ---------------------------------------------------------------------------


class TestSequenceNumbers:
    def test_first_emit_sequence_zero(self) -> None:
        emitter = AuditEmitter(_cfg())
        event = emitter.emit(_result(), "s1", None)
        assert event.sequence_number == 0

    def test_sequential_emits_monotonic(self) -> None:
        emitter = AuditEmitter(_cfg())
        events = [emitter.emit(_result(), "s1", None) for _ in range(5)]
        assert [e.sequence_number for e in events] == [0, 1, 2, 3, 4]

    def test_different_sessions_independent(self) -> None:
        emitter = AuditEmitter(_cfg())
        e1 = emitter.emit(_result(), "s1", None)
        e2 = emitter.emit(_result(), "s2", None)
        e3 = emitter.emit(_result(), "s1", None)
        assert e1.sequence_number == 0
        assert e2.sequence_number == 0
        assert e3.sequence_number == 1

    def test_none_session_uses_dedicated_counter(self) -> None:
        emitter = AuditEmitter(_cfg())
        e1 = emitter.emit(_result(), None, None)
        e2 = emitter.emit(_result(), "s1", None)
        e3 = emitter.emit(_result(), None, None)
        assert e1.sequence_number == 0
        assert e2.sequence_number == 0
        assert e3.sequence_number == 1

    def test_no_gaps_across_100_emits(self) -> None:
        emitter = AuditEmitter(_cfg())
        events = [emitter.emit(_result(), "s1", None) for _ in range(100)]
        assert [e.sequence_number for e in events] == list(range(100))


# ---------------------------------------------------------------------------
# Callback behavior
# ---------------------------------------------------------------------------


class TestCallbackBehavior:
    def test_no_callback_completes_without_error(self) -> None:
        emitter = AuditEmitter(_cfg(), on_audit=None)
        event = emitter.emit(_result(), "s1", None)
        assert event is not None

    def test_callback_receives_exact_event(self) -> None:
        received: list[AuditEvent] = []
        emitter = AuditEmitter(_cfg(), on_audit=received.append)
        event = emitter.emit(_result(), "s1", None)
        assert len(received) == 1
        assert received[0] is event

    def test_callback_raises_valueerror_wrapped_as_runtime(self) -> None:
        def bad_cb(e: AuditEvent) -> None:
            raise ValueError("bad")

        emitter = AuditEmitter(_cfg(), on_audit=bad_cb)
        with pytest.raises(RuntimeError, match="on_audit callback failed"):
            emitter.emit(_result(), "s1", None)

    def test_callback_raises_generic_exception_wrapped(self) -> None:
        def bad_cb(e: AuditEvent) -> None:
            raise Exception("generic")

        emitter = AuditEmitter(_cfg(), on_audit=bad_cb)
        with pytest.raises(RuntimeError, match="on_audit callback failed"):
            emitter.emit(_result(), "s1", None)


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


class TestEventTypes:
    def test_event_type_is_scan_complete(self) -> None:
        emitter = AuditEmitter(_cfg())
        event = emitter.emit(_result(), "s1", None)
        assert event.event_type == "scan_complete"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_findings_zero_count(self) -> None:
        emitter = AuditEmitter(_cfg(audit_verbosity="minimal"))
        event = emitter.emit(_result(findings=()), "s1", None)
        assert event.payload["finding_count"] == 0

    def test_freq_result_none_standard_payload(self) -> None:
        emitter = AuditEmitter(_cfg(audit_verbosity="standard"))
        event = emitter.emit(_result(), "s1", None)
        assert event.payload["session_score"] is None
        assert event.payload["escalation_tier"] is None

    def test_multiple_sessions_interleaved(self) -> None:
        emitter = AuditEmitter(_cfg())
        seq: dict[str, list[int]] = {"s1": [], "s2": [], "s3": []}
        for _ in range(3):
            for sid in ("s1", "s2", "s3"):
                e = emitter.emit(_result(), sid, None)
                seq[sid].append(e.sequence_number)
        assert seq["s1"] == [0, 1, 2]
        assert seq["s2"] == [0, 1, 2]
        assert seq["s3"] == [0, 1, 2]

    def test_payload_is_immutable(self) -> None:
        emitter = AuditEmitter(_cfg(audit_verbosity="minimal"))
        event = emitter.emit(_result(), "s1", None)
        with pytest.raises(TypeError):
            event.payload["injected"] = True  # type: ignore[index]

    def test_verbose_payload_redacts_hash_key(self) -> None:
        cfg = _cfg(
            audit_verbosity="verbose",
            anonymize=True,
            redaction_mode="hash",
            hash_key="super-secret-hmac-key-for-test",
        )
        emitter = AuditEmitter(cfg)
        event = emitter.emit(_result(), "s1", _freq_result())
        snapshot = event.payload["config_snapshot"]
        assert snapshot["hash_key"] == "[REDACTED]"

    def test_verbose_payload_no_raw_secret_in_str(self) -> None:
        raw_key = "super-secret-hmac-key-for-test"
        cfg = _cfg(
            audit_verbosity="verbose",
            anonymize=True,
            redaction_mode="hash",
            hash_key=raw_key,
        )
        emitter = AuditEmitter(cfg)
        event = emitter.emit(_result(), "s1", _freq_result())
        assert raw_key not in str(event.payload)

    def test_stale_session_pruning(self) -> None:
        cfg = _cfg(session_ttl_seconds=1.0)
        emitter = AuditEmitter(cfg)

        with patch("petasos.premium.audit.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            mock_time.time.return_value = 100.0
            emitter.emit(_result(), "old_session", None)

            mock_time.monotonic.return_value = 200.0
            mock_time.time.return_value = 200.0
            emitter.emit(_result(), "new_session", None)

        assert "old_session" not in emitter._sequence_counters
        assert "new_session" in emitter._sequence_counters
