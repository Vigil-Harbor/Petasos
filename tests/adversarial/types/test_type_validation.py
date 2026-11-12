"""Pin constructor validation, scanner structure and immutable result data."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from petasos.model import (
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


class TestPipelineResultImmutability:
    """Pin Pipeline Result Immutability."""

    def test_pipeline_result_dict_wrapped_as_proxy(self) -> None:
        """Pin pipeline result dict wrapped as proxy."""
        r = PipelineResult(
            safe=True,
            findings=(),
            feature_status={"frequency": "available"},  # type: ignore[arg-type]
        )
        assert isinstance(r.feature_status, MappingProxyType)

    def test_pipeline_result_proxy_mutation_raises(self) -> None:
        """Pin pipeline result proxy mutation raises."""
        r = PipelineResult(
            safe=True,
            findings=(),
            feature_status={"frequency": "available"},  # type: ignore[arg-type]
        )
        assert r.feature_status is not None
        with pytest.raises(TypeError):
            r.feature_status["frequency"] = "evil"  # type: ignore[index]

    def test_pipeline_result_none_stays_none(self) -> None:
        """Pin pipeline result none stays none."""
        r = PipelineResult(safe=True, findings=())
        assert r.feature_status is None

    def test_pipeline_result_proxy_not_double_wrapped(self) -> None:
        """Pin pipeline result proxy not double wrapped."""
        proxy = MappingProxyType({"frequency": "available"})
        r = PipelineResult(safe=True, findings=(), feature_status=proxy)
        assert r.feature_status is proxy


class TestPositionValidation:
    """Pin Position Validation."""

    def test_position_inverted_raises(self) -> None:
        """Pin position inverted raises."""
        with pytest.raises(ValueError, match="must be >= Position.start"):
            Position(start=10, end=5)

    def test_position_negative_start_raises(self) -> None:
        """Pin position negative start raises."""
        with pytest.raises(ValueError, match="must be >= 0"):
            Position(start=-1, end=5)

    def test_position_zero_length_accepted(self) -> None:
        """Pin position zero length accepted."""
        p = Position(start=5, end=5)
        assert p.start == 5
        assert p.end == 5


class TestConfidenceValidation:
    """Pin Confidence Validation."""

    def test_confidence_above_one_raises(self) -> None:
        """Pin confidence above one raises."""
        with pytest.raises(ValueError, match=r"must be in \[0\.0, 1\.0\]"):
            _make_finding(confidence=1.5)

    def test_confidence_below_zero_raises(self) -> None:
        """Pin confidence below zero raises."""
        with pytest.raises(ValueError, match=r"must be in \[0\.0, 1\.0\]"):
            _make_finding(confidence=-0.1)

    def test_confidence_nan_raises(self) -> None:
        """Pin confidence nan raises."""
        with pytest.raises(ValueError, match=r"must be in \[0\.0, 1\.0\]"):
            _make_finding(confidence=float("nan"))

    def test_confidence_inf_raises(self) -> None:
        """Pin confidence inf raises."""
        with pytest.raises(ValueError, match=r"must be in \[0\.0, 1\.0\]"):
            _make_finding(confidence=float("inf"))


class TestValidateScanner:
    """Pin Validate Scanner."""

    def test_validate_scanner_accepts_valid(self) -> None:
        """Pin validate scanner accepts valid."""
        _validate_scanner(MinimalScanner())

    def test_validate_scanner_missing_name(self) -> None:
        """Pin validate scanner missing name."""

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
        """Pin validate scanner missing scan."""

        class NoScan:
            @property
            def name(self) -> str:
                return "bad"

        with pytest.raises(TypeError, match="missing callable 'scan' method"):
            _validate_scanner(NoScan())

    def test_validate_scanner_sync_scan_rejected(self) -> None:
        """Pin validate scanner sync scan rejected."""

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
        """Pin validate scanner accepts kwargs scan."""

        class KwargsScanner:
            @property
            def name(self) -> str:
                return "kwargs"

            async def scan(self, text: str, **kwargs: object) -> ScanResult:
                return ScanResult(scanner_name="kwargs", findings=())

        _validate_scanner(KwargsScanner())

    def test_validate_scanner_rejects_scan_without_text(self) -> None:
        """Pin validate scanner rejects scan without text."""

        class KwargsOnlyScanner:
            @property
            def name(self) -> str:
                return "kwargs_only"

            async def scan(self, **kwargs: object) -> ScanResult:
                return ScanResult(scanner_name="kwargs_only", findings=())

        with pytest.raises(TypeError, match="missing 'text' parameter"):
            _validate_scanner(KwargsOnlyScanner())

    def test_pipeline_rejects_invalid_scanner(self) -> None:
        """Pin pipeline rejects invalid scanner."""

        class BadObj:
            pass

        with pytest.raises(TypeError):
            Pipeline(scanners=[BadObj()])  # type: ignore[list-item]


class TestRoundtripValidation:
    """Pin Roundtrip Validation."""

    def test_from_dict_roundtrip_preserves_validation(self) -> None:
        """Pin from dict roundtrip preserves validation."""
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
