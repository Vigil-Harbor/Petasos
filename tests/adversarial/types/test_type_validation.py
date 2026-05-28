from __future__ import annotations

from types import MappingProxyType

import pytest

from petasos._types import (
    PipelineResult,
    Position,
    ScanFinding,
    ScanResult,
    Severity,
    _validate_scanner,
)
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner


def _make_finding(*, confidence: float = 0.9) -> ScanFinding:
    return ScanFinding(
        rule_id="test.rule",
        finding_type="injection",
        severity=Severity.HIGH,
        confidence=confidence,
        message="test",
        scanner_name="test",
    )


# ---------------------------------------------------------------------------
# TYP-02: PipelineResult immutability enforcement
# ---------------------------------------------------------------------------


class TestPipelineResultImmutability:
    def test_pipeline_result_dict_wrapped_as_proxy(self) -> None:
        r = PipelineResult(
            safe=True,
            findings=(),
            premium_features={"frequency": "available"},  # type: ignore[arg-type]
        )
        assert isinstance(r.premium_features, MappingProxyType)

    def test_pipeline_result_proxy_mutation_raises(self) -> None:
        r = PipelineResult(
            safe=True,
            findings=(),
            premium_features={"frequency": "available"},  # type: ignore[arg-type]
        )
        assert r.premium_features is not None
        with pytest.raises(TypeError):
            r.premium_features["frequency"] = "evil"  # type: ignore[index]

    def test_pipeline_result_none_stays_none(self) -> None:
        r = PipelineResult(safe=True, findings=())
        assert r.premium_features is None

    def test_pipeline_result_proxy_not_double_wrapped(self) -> None:
        proxy = MappingProxyType({"frequency": "available"})
        r = PipelineResult(safe=True, findings=(), premium_features=proxy)
        assert r.premium_features is proxy


# ---------------------------------------------------------------------------
# TYP-03: Position + confidence validation
# ---------------------------------------------------------------------------


class TestPositionValidation:
    def test_position_inverted_raises(self) -> None:
        with pytest.raises(ValueError, match="must be >= Position.start"):
            Position(start=10, end=5)

    def test_position_negative_start_raises(self) -> None:
        with pytest.raises(ValueError, match="must be >= 0"):
            Position(start=-1, end=5)

    def test_position_zero_length_accepted(self) -> None:
        p = Position(start=5, end=5)
        assert p.start == 5
        assert p.end == 5


class TestConfidenceValidation:
    def test_confidence_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match=r"must be in \[0\.0, 1\.0\]"):
            _make_finding(confidence=1.5)

    def test_confidence_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match=r"must be in \[0\.0, 1\.0\]"):
            _make_finding(confidence=-0.1)

    def test_confidence_nan_raises(self) -> None:
        with pytest.raises(ValueError, match=r"must be in \[0\.0, 1\.0\]"):
            _make_finding(confidence=float("nan"))

    def test_confidence_inf_raises(self) -> None:
        with pytest.raises(ValueError, match=r"must be in \[0\.0, 1\.0\]"):
            _make_finding(confidence=float("inf"))


# ---------------------------------------------------------------------------
# TYP-04: Scanner validation
# ---------------------------------------------------------------------------


class TestValidateScanner:
    def test_validate_scanner_accepts_valid(self) -> None:
        _validate_scanner(MinimalScanner())

    def test_validate_scanner_missing_name(self) -> None:
        class NoName:
            async def scan(
                self,
                text: str,
                *,
                direction: str = "inbound",
                session_id: str | None = None,
            ) -> ScanResult:
                return ScanResult(scanner_name="x", findings=())

        with pytest.raises(TypeError, match="missing 'name' attribute"):
            _validate_scanner(NoName())

    def test_validate_scanner_missing_scan(self) -> None:
        class NoScan:
            @property
            def name(self) -> str:
                return "bad"

        with pytest.raises(TypeError, match="missing callable 'scan' method"):
            _validate_scanner(NoScan())

    def test_validate_scanner_sync_scan_rejected(self) -> None:
        class SyncScan:
            @property
            def name(self) -> str:
                return "sync"

            def scan(
                self,
                text: str,
                *,
                direction: str = "inbound",
                session_id: str | None = None,
            ) -> ScanResult:
                return ScanResult(scanner_name="sync", findings=())

        with pytest.raises(TypeError, match="must be async"):
            _validate_scanner(SyncScan())

    def test_validate_scanner_accepts_kwargs_scan(self) -> None:
        class KwargsScanner:
            @property
            def name(self) -> str:
                return "kwargs"

            async def scan(self, text: str, **kwargs: object) -> ScanResult:
                return ScanResult(scanner_name="kwargs", findings=())

        _validate_scanner(KwargsScanner())

    def test_pipeline_rejects_invalid_scanner(self) -> None:
        class BadObj:
            pass

        with pytest.raises(TypeError):
            Pipeline(scanners=[BadObj()])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# Cross-cutting
# ---------------------------------------------------------------------------


class TestRoundtripValidation:
    def test_from_dict_roundtrip_preserves_validation(self) -> None:
        f = _make_finding(confidence=0.8)
        d = f.to_dict()
        f2 = ScanFinding.from_dict(d)
        assert f2.confidence == 0.8

        d["confidence"] = 2.0
        with pytest.raises(ValueError, match=r"must be in \[0\.0, 1\.0\]"):
            ScanFinding.from_dict(d)

        d["confidence"] = 0.5
        d["position"] = {"start": 10, "end": 5}
        with pytest.raises(ValueError, match="must be >= Position.start"):
            ScanFinding.from_dict(d)
