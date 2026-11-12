"""Pin finite confidence bounds and severity-first overlap resolution.

See docs/architecture/rationale.md, "Test timing and backend qualification"."""

from __future__ import annotations

from typing import Any

from petasos.model import Position, ScanFinding, ScanResult, Severity
from petasos.pipeline.findings import merge_findings
from petasos.scanners.presidio import PresidioScanner


class _FakePresidioResult:
    def __init__(self, score: float) -> None:
        self.entity_type = "EMAIL_ADDRESS"
        self.score = score
        self.start = 0
        self.end = 3


class _FakeAnalyzer:
    def __init__(self, score: float) -> None:
        self._score = score

    def analyze(self, **kwargs: Any) -> list[_FakePresidioResult]:
        """Provide analyze for the test fixture."""
        return [_FakePresidioResult(self._score)]


def test_presidio_confidence_clamped() -> None:
    """Pin presidio confidence clamped."""
    high = PresidioScanner()
    high._analyzer = _FakeAnalyzer(99.0)
    high._loaded = True
    assert high._scan_sync("abc")[0].confidence == 1.0

    nan = PresidioScanner()
    nan._analyzer = _FakeAnalyzer(float("nan"))
    nan._loaded = True
    # CPython max/min does not reliably clamp NaN; the finite guard must map it to zero.
    assert nan._scan_sync("abc")[0].confidence == 0.0


def test_overlap_resolve_severity_first() -> None:
    """Pin overlap resolve severity first."""
    high_sev_low_conf = ScanFinding(
        rule_id="a",
        finding_type="injection",
        severity=Severity.CRITICAL,
        confidence=0.40,
        message="m",
        scanner_name="s",
        position=Position(start=0, end=10),
    )
    low_sev_high_conf = ScanFinding(
        rule_id="b",
        finding_type="pii",
        severity=Severity.LOW,
        confidence=0.99,
        message="m",
        scanner_name="s",
        position=Position(start=5, end=15),
    )
    merged = merge_findings(
        [ScanResult(scanner_name="s", findings=(high_sev_low_conf, low_sev_high_conf))]
    )
    assert len(merged) == 1
    assert merged[0].severity == Severity.CRITICAL
