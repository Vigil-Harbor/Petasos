from __future__ import annotations

import uuid
from types import MappingProxyType
from unittest.mock import patch

import pytest

from petasos._types import AuditEvent, PipelineResult, ScanFinding, ScanResult, Severity
from petasos.config import PetasosConfig
from petasos.premium.audit import AuditEmitter
from petasos.premium.frequency import FrequencyUpdateResult


class _AuditCallbackKill(BaseException):
    """A BaseException (not an Exception) raised by a callback.

    Used to prove emit() isolates BaseException subclasses, not just Exception —
    the pre-fix code caught only ``Exception`` and re-raised, so this would have
    propagated straight through inspect().
    """


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

    def test_different_sessions_global_sequence(self) -> None:
        emitter = AuditEmitter(_cfg())
        e1 = emitter.emit(_result(), "s1", None)
        e2 = emitter.emit(_result(), "s2", None)
        e3 = emitter.emit(_result(), "s1", None)
        assert e1.sequence_number == 0
        assert e2.sequence_number == 1
        assert e3.sequence_number == 2

    def test_none_session_shares_global_counter(self) -> None:
        emitter = AuditEmitter(_cfg())
        e1 = emitter.emit(_result(), None, None)
        e2 = emitter.emit(_result(), "s1", None)
        e3 = emitter.emit(_result(), None, None)
        assert e1.sequence_number == 0
        assert e2.sequence_number == 1
        assert e3.sequence_number == 2

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

    def test_callback_raises_valueerror_swallowed(self) -> None:
        def bad_cb(e: AuditEvent) -> None:
            raise ValueError("bad")

        emitter = AuditEmitter(_cfg(), on_audit=bad_cb)
        event = emitter.emit(_result(), "s1", None)
        assert event is not None
        assert emitter.last_callback_error is not None
        assert "ValueError" in emitter.last_callback_error
        assert "bad" in emitter.last_callback_error

    def test_callback_raises_generic_exception_swallowed(self) -> None:
        def bad_cb(e: AuditEvent) -> None:
            raise Exception("generic")

        emitter = AuditEmitter(_cfg(), on_audit=bad_cb)
        event = emitter.emit(_result(), "s1", None)
        assert event is not None
        assert emitter.last_callback_error is not None
        assert "generic" in emitter.last_callback_error


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

    def test_multiple_sessions_interleaved_global(self) -> None:
        emitter = AuditEmitter(_cfg())
        seq: dict[str, list[int]] = {"s1": [], "s2": [], "s3": []}
        for _ in range(3):
            for sid in ("s1", "s2", "s3"):
                e = emitter.emit(_result(), sid, None)
                seq[sid].append(e.sequence_number)
        assert seq["s1"] == [0, 3, 6]
        assert seq["s2"] == [1, 4, 7]
        assert seq["s3"] == [2, 5, 8]

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

    def test_global_sequence_continues_across_sessions(self) -> None:
        emitter = AuditEmitter(_cfg())
        e1 = emitter.emit(_result(), "s1", None)
        e2 = emitter.emit(_result(), "s2", None)
        e3 = emitter.emit(_result(), "s1", None)
        assert e1.sequence_number == 0
        assert e2.sequence_number == 1
        assert e3.sequence_number == 2
        assert emitter._global_sequence == 3


# ---------------------------------------------------------------------------
# AUD-01 (PET-20) — sequence chain survives session churn / TTL prune
#
# Regression for: "Reuse session_id after TTL prune -> sequence_number resets
# to 0". The pre-fix emitter kept a per-session counter pruned on TTL, so a
# reconnecting session restarted at 0 and the cross-session sequence had
# duplicate values. The global monotonic counter is immune. Each test below
# FAILS against the pre-fix per-session implementation and PASSES post-fix.
# ---------------------------------------------------------------------------


class TestSequenceAdversarial:
    def test_reconnect_after_session_churn_no_reset(self) -> None:
        emitter = AuditEmitter(_cfg())
        first = emitter.emit(_result(), "agent-A", None)
        for i in range(50):
            emitter.emit(_result(), f"churn-{i}", None)
        again = emitter.emit(_result(), "agent-A", None)

        assert first.sequence_number == 0
        # Pre-fix (per-session counter) would give agent-A its own seq == 1 here.
        assert again.sequence_number == 51
        assert again.sequence_number > first.sequence_number

    def test_sequence_globally_unique_under_session_reuse(self) -> None:
        emitter = AuditEmitter(_cfg())
        seqs: list[int] = []
        for _ in range(4):
            for sid in ("a", "b", "c"):
                seqs.append(emitter.emit(_result(), sid, None).sequence_number)

        # Pre-fix per-session counters produce duplicates ([0,0,0,1,1,1,...]).
        assert len(set(seqs)) == len(seqs)
        assert seqs == sorted(seqs)
        assert seqs == list(range(12))

    def test_sequence_does_not_reset_after_ttl_prune(self) -> None:
        # Literal AUD-01 attack: let a session's TTL elapse (which pre-fix would
        # prune), churn other sessions, then reconnect the original session_id.
        emitter = AuditEmitter(_cfg(session_ttl_seconds=10.0))
        with patch("petasos.premium.audit.time") as mock_time:
            mock_time.time.return_value = 2000.0

            mock_time.monotonic.return_value = 1000.0
            first = emitter.emit(_result(), "agent-A", None)

            # Advance well past the TTL while other sessions emit.
            mock_time.monotonic.return_value = 1000.0 + 100.0
            for i in range(5):
                emitter.emit(_result(), f"churn-{i}", None)

            # agent-A reconnects after its counter would have been pruned.
            again = emitter.emit(_result(), "agent-A", None)

        assert first.sequence_number == 0
        # Pre-fix: pruned counter -> reconnect restarts at 0.
        assert again.sequence_number == 6
        assert again.sequence_number > first.sequence_number


# ---------------------------------------------------------------------------
# AUD-02 (PET-21) — on_audit callback failures never reach the pipeline
#
# Regression for: "on_audit raises RuntimeError -> propagates to pipeline,
# breaking the never-throws invariant". The pre-fix emit() re-raised as
# RuntimeError (and caught only Exception, so BaseException escaped entirely).
# Post-fix swallows BaseException, logs with exc_info, and records the error
# in last_callback_error for the pipeline hook to fold into PipelineResult.errors.
# ---------------------------------------------------------------------------


class TestCallbackIsolationAdversarial:
    def test_emit_does_not_raise_on_runtimeerror_callback(self) -> None:
        def bad_cb(_: AuditEvent) -> None:
            raise RuntimeError("on_audit boom")

        emitter = AuditEmitter(_cfg(), on_audit=bad_cb)
        # Pre-fix this call raised RuntimeError; the assertions below were never
        # reached. Post-fix it returns normally.
        event = emitter.emit(_result(), "s1", None)
        assert event is not None
        assert emitter.last_callback_error is not None
        assert "RuntimeError" in emitter.last_callback_error
        assert "on_audit boom" in emitter.last_callback_error

    def test_emit_swallows_baseexception_subclass(self) -> None:
        def bad_cb(_: AuditEvent) -> None:
            raise _AuditCallbackKill("base-level kill")

        emitter = AuditEmitter(_cfg(), on_audit=bad_cb)
        # Pre-fix caught only Exception, so this BaseException propagated.
        event = emitter.emit(_result(), "s1", None)
        assert event is not None
        assert emitter.last_callback_error is not None
        assert "_AuditCallbackKill" in emitter.last_callback_error

    def test_callback_error_cleared_on_next_success(self) -> None:
        state = {"fail": True}

        def cb(_: AuditEvent) -> None:
            if state["fail"]:
                raise RuntimeError("first emit fails")

        emitter = AuditEmitter(_cfg(), on_audit=cb)
        emitter.emit(_result(), "s1", None)
        assert emitter.last_callback_error is not None

        state["fail"] = False
        emitter.emit(_result(), "s1", None)
        # A clean emit must not carry the prior error into PipelineResult.errors.
        assert emitter.last_callback_error is None

    def test_sequence_advances_despite_callback_failure(self) -> None:
        def bad_cb(_: AuditEvent) -> None:
            raise RuntimeError("always boom")

        emitter = AuditEmitter(_cfg(), on_audit=bad_cb)
        e1 = emitter.emit(_result(), "s1", None)
        e2 = emitter.emit(_result(), "s1", None)
        # The event is still fully formed and the chain advances even though the
        # callback failed on every emit.
        assert e1.sequence_number == 0
        assert e2.sequence_number == 1
