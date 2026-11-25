"""Pin validated immutable result types and structural scanner contracts."""

from __future__ import annotations

import dataclasses
import json
from types import MappingProxyType

import pytest

from petasos.model import (
    Alert,
    AuditEvent,
    NormalizedText,
    PipelineResult,
    Position,
    ScanCoverage,
    ScanFinding,
    Scanner,
    ScanResult,
    Severity,
    severity_rank,
)


class _StubScanner:
    @property
    def name(self) -> str:
        return "stub"

    async def scan(
        self,
        text: str,
        *,
        direction: str = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        return ScanResult(scanner_name=self.name, findings=())


def _sample_finding() -> ScanFinding:
    return ScanFinding(
        rule_id="test.rule",
        finding_type="injection",
        severity=Severity.HIGH,
        confidence=0.95,
        message="test finding",
        scanner_name="test",
        position=Position(start=0, end=5),
        matched_text="hello",
    )


class TestScannerProtocol:
    def test_runtime_checkable(self) -> None:
        stub = _StubScanner()
        assert isinstance(stub, Scanner)

    def test_stub_satisfies_protocol(self) -> None:
        stub = _StubScanner()
        assert hasattr(stub, "name")
        assert hasattr(stub, "scan")

    async def test_stub_scan_returns_scan_result(self) -> None:
        stub = _StubScanner()
        result = await stub.scan("hello")
        assert isinstance(result, ScanResult)
        assert result.scanner_name == "stub"


class TestScanFinding:
    def test_frozen(self) -> None:
        f = _sample_finding()
        with pytest.raises(dataclasses.FrozenInstanceError):
            f.rule_id = "other"  # type: ignore[misc]

    def test_to_dict_roundtrip(self) -> None:
        f = _sample_finding()
        d = f.to_dict()
        serialized = json.dumps(d)
        deserialized = json.loads(serialized)
        f2 = ScanFinding.from_dict(deserialized)
        assert f == f2

    def test_to_dict_without_position(self) -> None:
        f = ScanFinding(
            rule_id="test.rule",
            finding_type="injection",
            severity=Severity.LOW,
            confidence=0.5,
            message="no position",
            scanner_name="test",
        )
        d = f.to_dict()
        assert d["position"] is None
        assert d["matched_text"] is None
        f2 = ScanFinding.from_dict(d)
        assert f == f2

    def test_severity_serialized_as_value(self) -> None:
        f = _sample_finding()
        d = f.to_dict()
        assert d["severity"] == "high"


class TestScanResult:
    def test_legacy_serialization_omits_coverage(self) -> None:
        payload = {"scanner_name": "test", "findings": [], "duration_ms": 0.0, "error": None}
        assert ScanResult("test", ()).to_dict() == payload
        assert ScanResult.from_dict(payload).to_dict() == payload

    def test_coverage_roundtrip(self) -> None:
        coverage = ScanCoverage("no_targets", 5, 5, 0, 0)
        result = ScanResult("semgrep", (), coverage=coverage)
        assert ScanResult.from_dict(json.loads(json.dumps(result.to_dict()))) == result

    def test_frozen(self) -> None:
        r = ScanResult(scanner_name="test", findings=())
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.scanner_name = "other"  # type: ignore[misc]

    def test_empty_findings(self) -> None:
        r = ScanResult(scanner_name="test", findings=())
        assert r.findings == ()
        assert r.error is None

    def test_with_error(self) -> None:
        r = ScanResult(scanner_name="test", findings=(), error="something broke")
        assert r.error == "something broke"

    def test_to_dict_roundtrip(self) -> None:
        f = _sample_finding()
        r = ScanResult(scanner_name="test", findings=(f,), duration_ms=1.5)
        d = r.to_dict()
        serialized = json.dumps(d)
        deserialized = json.loads(serialized)
        r2 = ScanResult.from_dict(deserialized)
        assert r == r2


class TestPipelineResult:
    def test_field_types_resolve_at_runtime(self) -> None:
        import typing

        for cls in (PipelineResult, ScanResult, ScanFinding):
            assert typing.get_type_hints(cls)

    def test_legacy_serialization_omits_backend_coverage(self) -> None:
        assert PipelineResult(True, ()).to_dict() == {
            "safe": True,
            "findings": [],
            "sanitized_content": None,
            "scanner_results": [],
            "errors": [],
            "escalation_tier": None,
            "session_score": None,
            "feature_status": None,
        }

    def test_backend_coverage_is_defensively_frozen(self) -> None:
        coverage = ScanCoverage("no_targets", 5, 5, 0, 0)
        original = {"semgrep": coverage}
        result = PipelineResult(True, (), backend_coverage=original)
        original.clear()
        assert result.backend_coverage is not None
        assert result.backend_coverage["semgrep"] == coverage
        with pytest.raises(TypeError):
            result.backend_coverage["semgrep"] = coverage  # type: ignore[index]
        assert result.to_dict()["backend_coverage"] == {"semgrep": coverage.to_dict()}

    def test_frozen(self) -> None:
        r = PipelineResult(safe=True, findings=())
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.safe = False  # type: ignore[misc]


class TestNormalizedText:
    def test_frozen(self) -> None:
        n = NormalizedText(original="hello", normalized="hello", transformations_applied=())
        assert n.composed_views == ()
        with pytest.raises(dataclasses.FrozenInstanceError):
            n.normalized = "other"  # type: ignore[misc]


class TestPosition:
    def test_named_fields(self) -> None:
        p = Position(start=0, end=5)
        assert p.start == 0
        assert p.end == 5


class TestSeverity:
    def test_values(self) -> None:
        assert Severity.CRITICAL.value == "critical"
        assert Severity.HIGH.value == "high"
        assert Severity.MEDIUM.value == "medium"
        assert Severity.LOW.value == "low"
        assert Severity.INFO.value == "info"


class TestDirection:
    def test_accepts_inbound_outbound(self) -> None:
        from petasos.model import Direction

        inbound: Direction = "inbound"
        outbound: Direction = "outbound"
        assert inbound == "inbound"
        assert outbound == "outbound"


class TestFrozenDataclasses:
    def test_scan_finding_frozen(self) -> None:
        f = ScanFinding(
            rule_id="test",
            finding_type="test",
            severity=Severity.LOW,
            confidence=0.5,
            message="test",
            scanner_name="test",
        )
        with pytest.raises(AttributeError):
            f.rule_id = "hacked"  # type: ignore[misc]

    def test_scan_result_frozen(self) -> None:
        r = ScanResult(scanner_name="test", findings=())
        with pytest.raises(AttributeError):
            r.scanner_name = "hacked"  # type: ignore[misc]

    def test_pipeline_result_frozen(self) -> None:
        r = PipelineResult(safe=True, findings=())
        with pytest.raises(AttributeError):
            r.safe = False  # type: ignore[misc]

    def test_audit_event_frozen(self) -> None:
        e = AuditEvent(
            event_id="e1",
            timestamp=0.0,
            session_id=None,
            event_type="test",
            payload=MappingProxyType({}),
            sequence_number=0,
        )
        with pytest.raises(AttributeError):
            e.event_type = "hacked"  # type: ignore[misc]

    def test_alert_frozen(self) -> None:
        a = Alert(
            alert_id="a1",
            timestamp=0.0,
            rule_id="r1",
            severity="high",
            session_id=None,
            message="test",
            context=MappingProxyType({}),
        )
        with pytest.raises(AttributeError):
            a.message = "hacked"  # type: ignore[misc]


class TestDefensiveCopies:
    def test_pipeline_result_findings_is_tuple(self) -> None:
        r = PipelineResult(safe=True, findings=())
        assert isinstance(r.findings, tuple)

    def test_pipeline_result_scanner_results_is_tuple(self) -> None:
        r = PipelineResult(safe=True, findings=(), scanner_results=())
        assert isinstance(r.scanner_results, tuple)

    def test_pipeline_result_errors_is_tuple(self) -> None:
        r = PipelineResult(safe=True, findings=(), errors=())
        assert isinstance(r.errors, tuple)


def test_pipeline_result_to_dict_serializes_nested() -> None:
    finding = ScanFinding(
        rule_id="petasos.presidio.email",
        finding_type="pii",
        severity=Severity.HIGH,
        confidence=0.9,
        message="email address detected",
        scanner_name="presidio",
        position=Position(start=0, end=4),
        matched_text="a@b.c",
    )
    sr = ScanResult(scanner_name="presidio", findings=(finding,), duration_ms=1.0, error=None)
    result = PipelineResult(
        safe=False,
        findings=(finding,),
        scanner_results=(sr,),
        errors=("boom",),
        feature_status=MappingProxyType({"audit": "enabled"}),
    )
    d = result.to_dict()
    assert d["safe"] is False
    assert d["findings"][0]["severity"] == "high"
    assert d["scanner_results"][0]["scanner_name"] == "presidio"
    assert d["errors"] == ["boom"]
    assert d["feature_status"] == {"audit": "enabled"}


def test_unknown_severity_and_audit_dicts_round_trip() -> None:
    assert severity_rank("not-a-severity") < severity_rank(Severity.INFO)
    assert severity_rank("not-a-severity", unknown_wins=True) > severity_rank(Severity.CRITICAL)
    payload = MappingProxyType({"sev": Severity.HIGH, "items": [{"nested": 1}]})
    event = AuditEvent("e", 1.0, "s", "scan", payload, 1)
    assert event.to_dict()["payload"]["sev"] == "high"
    alert = Alert("a", 1.0, "rule", "high", "s", "msg", payload)
    assert alert.to_dict()["context"]["items"] == [{"nested": 1}]


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


class TestPipelineResultFields:
    def test_escalation_tier_defaults_to_none(self) -> None:
        result = PipelineResult(safe=True, findings=())
        assert result.escalation_tier is None

    def test_session_score_defaults_to_none(self) -> None:
        result = PipelineResult(safe=True, findings=())
        assert result.session_score is None
