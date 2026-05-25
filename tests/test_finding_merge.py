from __future__ import annotations

from petasos._types import Position, ScanFinding, ScanResult, Severity
from petasos.pipeline import merge_findings


def _finding(
    *,
    rule_id: str = "test.rule",
    severity: Severity = Severity.MEDIUM,
    confidence: float = 0.9,
    scanner_name: str = "scanner-a",
    start: int | None = None,
    end: int | None = None,
) -> ScanFinding:
    pos = Position(start=start, end=end) if start is not None and end is not None else None
    return ScanFinding(
        rule_id=rule_id,
        finding_type="injection",
        severity=severity,
        confidence=confidence,
        message="test finding",
        scanner_name=scanner_name,
        position=pos,
    )


def _result(findings: list[ScanFinding], scanner_name: str = "scanner-a") -> ScanResult:
    return ScanResult(scanner_name=scanner_name, findings=tuple(findings))


class TestMergeFindingsEmpty:
    def test_no_findings(self) -> None:
        assert merge_findings([]) == ()

    def test_empty_results(self) -> None:
        r = _result([])
        assert merge_findings([r]) == ()


class TestMergeFindingsNonOverlapping:
    def test_single_finding(self) -> None:
        f = _finding(start=0, end=5)
        merged = merge_findings([_result([f])])
        assert len(merged) == 1
        assert merged[0] is f

    def test_non_overlapping_preserved_in_order(self) -> None:
        f1 = _finding(start=0, end=5)
        f2 = _finding(start=10, end=15)
        f3 = _finding(start=20, end=25)
        merged = merge_findings([_result([f1, f2, f3])])
        assert len(merged) == 3
        assert merged[0] is f1
        assert merged[1] is f2
        assert merged[2] is f3

    def test_many_from_multiple_scanners(self) -> None:
        f1 = _finding(start=0, end=5, scanner_name="a")
        f2 = _finding(start=10, end=15, scanner_name="b")
        merged = merge_findings([_result([f1], "a"), _result([f2], "b")])
        assert len(merged) == 2


class TestMergeFindingsOverlapping:
    def test_higher_confidence_wins(self) -> None:
        f_low = _finding(start=0, end=10, confidence=0.7, scanner_name="a")
        f_high = _finding(start=5, end=15, confidence=0.9, scanner_name="b")
        merged = merge_findings([_result([f_low], "a"), _result([f_high], "b")])
        assert len(merged) == 1
        assert merged[0] is f_high

    def test_equal_confidence_higher_severity_wins(self) -> None:
        f_med = _finding(start=0, end=10, confidence=0.9, severity=Severity.MEDIUM)
        f_high = _finding(start=5, end=15, confidence=0.9, severity=Severity.HIGH)
        merged = merge_findings([_result([f_med]), _result([f_high])])
        assert len(merged) == 1
        assert merged[0] is f_high

    def test_double_tie_both_kept(self) -> None:
        f1 = _finding(start=0, end=10, confidence=0.9, severity=Severity.HIGH, scanner_name="a")
        f2 = _finding(start=5, end=15, confidence=0.9, severity=Severity.HIGH, scanner_name="b")
        merged = merge_findings([_result([f1], "a"), _result([f2], "b")])
        assert len(merged) == 2

    def test_same_position_different_scanners(self) -> None:
        f1 = _finding(start=0, end=10, confidence=0.8, scanner_name="a")
        f2 = _finding(start=0, end=10, confidence=0.95, scanner_name="b")
        merged = merge_findings([_result([f1], "a"), _result([f2], "b")])
        assert len(merged) == 1
        assert merged[0] is f2


class TestMergeFindingsUnpositioned:
    def test_unpositioned_always_kept(self) -> None:
        f_pos = _finding(start=0, end=10)
        f_unpos = _finding()
        merged = merge_findings([_result([f_pos, f_unpos])])
        assert len(merged) == 2
        assert f_unpos in merged

    def test_only_unpositioned(self) -> None:
        f1 = _finding()
        f2 = _finding(scanner_name="b")
        merged = merge_findings([_result([f1]), _result([f2], "b")])
        assert len(merged) == 2

    def test_mixed_positioned_and_unpositioned(self) -> None:
        f_pos1 = _finding(start=0, end=5)
        f_unpos = _finding()
        f_pos2 = _finding(start=10, end=15)
        merged = merge_findings([_result([f_pos1, f_unpos, f_pos2])])
        assert len(merged) == 3
