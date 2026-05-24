from __future__ import annotations

import dataclasses
import json

import pytest

from petasos._types import (
    NormalizedText,
    PipelineResult,
    Position,
    ScanFinding,
    Scanner,
    ScanResult,
    Severity,
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
    def test_frozen(self) -> None:
        r = PipelineResult(safe=True, findings=())
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.safe = False  # type: ignore[misc]


class TestNormalizedText:
    def test_frozen(self) -> None:
        n = NormalizedText(
            original="hello", normalized="hello", transformations_applied=()
        )
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
        from petasos._types import Direction

        inbound: Direction = "inbound"
        outbound: Direction = "outbound"
        assert inbound == "inbound"
        assert outbound == "outbound"
