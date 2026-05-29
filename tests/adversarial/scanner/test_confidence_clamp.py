"""PET-60 backfill: SCAN-02 confidence clamp + severity-first overlap.

White-box tests that drive each scanner's clamp via its ``_scan_sync`` with
stub backends — no ML extras required. The NaN cases pin the fail-safe
*direction*: a non-finite confidence must map to 0.0 (no signal), not the 1.0 a
bare ``max(0.0, min(1.0, raw))`` clamp would produce in CPython.
"""

from __future__ import annotations

from typing import Any

from petasos._types import Position, ScanFinding, ScanResult, Severity
from petasos.pipeline import merge_findings
from petasos.scanners.llama_firewall import LlamaFirewallScanner
from petasos.scanners.llm_guard import LlmGuardScanner
from petasos.scanners.presidio import PresidioScanner

# --- llm_guard --------------------------------------------------------------


class _FakeSubScanner:
    """Stand-in llm_guard sub-scanner: returns (sanitized, is_valid, risk_score)."""

    def __init__(self, risk_score: float) -> None:
        self._risk_score = risk_score

    def scan(self, text: str) -> tuple[str, bool, float]:
        return ("", False, self._risk_score)


def _llm_guard_with_score(score: float) -> LlmGuardScanner:
    scanner = LlmGuardScanner()
    scanner._scanners = [
        ("petasos.llmguard.injection", "injection", Severity.HIGH, _FakeSubScanner(score))
    ]
    scanner._loaded = True
    return scanner


def test_confidence_clamped_high() -> None:
    findings, errors = _llm_guard_with_score(99.0)._scan_sync("x")
    assert errors == []
    assert findings[0].confidence == 1.0


def test_confidence_clamped_negative() -> None:
    findings, _errors = _llm_guard_with_score(-5.0)._scan_sync("x")
    assert findings[0].confidence == 0.0


def test_confidence_clamped_nan() -> None:
    findings, _errors = _llm_guard_with_score(float("nan"))._scan_sync("x")
    # CPython trap: max(0.0, min(1.0, nan)) == 1.0 — NaN compares unordered, so
    # the first operand wins and a non-finite score inflates to MAX risk. The
    # isfinite guard maps it to 0.0 instead (unknown confidence = no signal, not
    # max signal). A bare max/min clamp would fail this assertion.
    assert findings[0].confidence == 0.0


# --- presidio ---------------------------------------------------------------


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
        return [_FakePresidioResult(self._score)]


def test_presidio_confidence_clamped() -> None:
    high = PresidioScanner()
    high._analyzer = _FakeAnalyzer(99.0)
    high._loaded = True
    assert high._scan_sync("abc")[0].confidence == 1.0

    nan = PresidioScanner()
    nan._analyzer = _FakeAnalyzer(float("nan"))
    nan._loaded = True
    # same CPython max/min NaN trap — the isfinite guard maps to 0.0, not 1.0
    assert nan._scan_sync("abc")[0].confidence == 0.0


# --- llama_firewall ---------------------------------------------------------


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeFwResult:
    def __init__(self, score: float) -> None:
        self.decision = "BLOCK"
        self.score = score
        self.reason = "flagged"


class _FakeFirewall:
    def __init__(self, score: float) -> None:
        self._score = score

    def scan(self, message: Any) -> _FakeFwResult:
        return _FakeFwResult(self._score)


def test_llama_confidence_nan() -> None:
    scanner = LlamaFirewallScanner()
    scanner._allow_decision = "ALLOW"
    scanner._user_message_cls = _FakeMessage
    scanner._assistant_message_cls = _FakeMessage
    scanner._components = {"prompt_guard": _FakeFirewall(float("nan"))}
    findings, _errors = scanner._scan_sync("text", "inbound")
    # NaN raw score → fail-safe 0.0 (not the 1.0 a bare max/min clamp yields)
    assert findings[0].confidence == 0.0


# --- overlap resolution -----------------------------------------------------


def test_overlap_resolve_severity_first() -> None:
    # PET-60 decision: overlapping findings resolve severity-first, NOT
    # highest-confidence. A more-severe finding wins over an overlapping
    # higher-confidence weaker one.
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
    assert merged[0].severity == Severity.CRITICAL  # severity beats confidence
