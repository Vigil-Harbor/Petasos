"""PET-109: cross-scanner suppression (pre-merge), PII severity downgrade, and the
config.pii_entities anonymize-stage filter (D5/D6/D7/D8).

These pipeline tests use a small in-test stub Scanner emitting fixed
``petasos.presidio.*`` findings, so they need no real Presidio and run on every
lane — except the single hash-mode D7 row, which exercises the anonymizer engine
path and is gated on the presidio libraries.
"""

from __future__ import annotations

import asyncio

import pytest

from petasos._types import Direction, Position, ScanFinding, ScanResult, Severity
from petasos.config import PetasosConfig
from petasos.pipeline import Pipeline, _is_floor_rule, _suppress_scanner_findings

_INJECTION_ID = "petasos.syntactic.injection.role-switch-capability"  # a floor rule

_presidio_libs = True
try:
    import presidio_analyzer  # noqa: F401
    import presidio_anonymizer  # noqa: F401
except ImportError:
    _presidio_libs = False

requires_presidio_libs = pytest.mark.skipif(
    not _presidio_libs, reason="presidio-analyzer + presidio-anonymizer required"
)


def _pii(
    rule_id: str,
    *,
    start: int,
    end: int,
    matched: str | None = None,
    severity: Severity = Severity.MEDIUM,
    confidence: float = 0.9,
) -> ScanFinding:
    return ScanFinding(
        rule_id=rule_id,
        finding_type="pii",
        severity=severity,
        confidence=confidence,
        message="pii",
        scanner_name="presidio",
        position=Position(start=start, end=end),
        matched_text=matched,
    )


def _injection(start: int = 0, end: int = 10) -> ScanFinding:
    return ScanFinding(
        rule_id=_INJECTION_ID,
        finding_type="injection",
        severity=Severity.HIGH,
        confidence=1.0,
        message="injection",
        scanner_name="presidio",
        position=Position(start=start, end=end),
    )


class _StubScanner:
    """Emits a fixed set of findings regardless of input text (name != 'minimal',
    so the pipeline routes it as an ML scanner)."""

    def __init__(self, findings: tuple[ScanFinding, ...], name: str = "presidio") -> None:
        self._findings = findings
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def scan(
        self, text: str, *, direction: Direction = "inbound", session_id: str | None = None
    ) -> ScanResult:
        return ScanResult(scanner_name=self._name, findings=self._findings, duration_ms=0.0)


# ---------------------------------------------------------------------------
# Cross-scanner suppression + downgrade
# ---------------------------------------------------------------------------


def test_profile_suppresses_presidio_finding_end_to_end() -> None:
    stub = _StubScanner((_pii("petasos.presidio.location", start=0, end=5),))
    p = Pipeline(scanners=[stub])
    result = asyncio.run(
        p.inspect("hello world", profile={"suppress_rules": ["petasos.presidio.location"]})
    )
    assert not any(f.rule_id == "petasos.presidio.location" for f in result.findings)
    # control: without suppression the finding is present
    plain = asyncio.run(p.inspect("hello world"))
    assert any(f.rule_id == "petasos.presidio.location" for f in plain.findings)


def test_suppress_cannot_silence_injection_or_structural() -> None:
    # End-to-end: a profile attempting to suppress a floor (injection) rule is a
    # no-op — the injection finding still fires.
    stub = _StubScanner((_injection(),))
    p = Pipeline(scanners=[stub])
    result = asyncio.run(p.inspect("payload", profile={"suppress_rules": [_INJECTION_ID]}))
    assert any(f.rule_id == _INJECTION_ID for f in result.findings)
    assert result.safe is False  # HIGH injection still blocks


def test_suppress_helper_honors_floor_directly() -> None:
    # Defense-in-depth (D6): even a suppress set that contains a floor rule (which
    # the profile layer would normally strip) cannot drop it at the pipeline stage.
    results = [ScanResult(scanner_name="stub", findings=(_injection(),), duration_ms=0.0)]
    out = _suppress_scanner_findings(results, frozenset({_INJECTION_ID}))
    assert _is_floor_rule(_INJECTION_ID) is True
    assert len(out[0].findings) == 1
    assert out[0].findings[0].rule_id == _INJECTION_ID


def test_severity_override_can_downgrade_pii() -> None:
    stub = _StubScanner(
        (
            _pii("petasos.presidio.person", start=0, end=5, severity=Severity.MEDIUM),
            _injection(start=10, end=20),
        )
    )
    p = Pipeline(scanners=[stub])
    result = asyncio.run(
        p.inspect(
            "name here payload here",
            profile={
                "severity_overrides": {
                    "petasos.presidio.person": "info",
                    _INJECTION_ID: "info",  # injection downgrade must be refused
                }
            },
        )
    )
    by_rule = {f.rule_id: f for f in result.findings}
    assert by_rule["petasos.presidio.person"].severity == Severity.INFO  # downgraded
    assert by_rule[_INJECTION_ID].severity == Severity.HIGH  # refused downgrade


def test_suppressed_finding_does_not_escalate() -> None:
    # Three CRITICAL findings would trip the standalone tier-3 net (>=3 CRITICAL);
    # suppressing them pre-merge removes that contribution (D5 ordering guard).
    crits = tuple(
        _pii("petasos.presidio.location", start=i, end=i + 3, severity=Severity.CRITICAL)
        for i in (0, 4, 8)
    )
    stub = _StubScanner(crits)
    p = Pipeline(scanners=[stub])

    control = asyncio.run(p.inspect("abcdefghijkl", session_id="s1"))
    assert control.escalation_tier == "tier3"  # the findings WOULD escalate
    assert control.safe is False

    suppressed = asyncio.run(
        p.inspect(
            "abcdefghijkl",
            session_id="s2",
            profile={"suppress_rules": ["petasos.presidio.location"]},
        )
    )
    assert suppressed.findings == ()
    assert suppressed.escalation_tier != "tier3"


def test_suppressed_overlap_does_not_evict_legitimate() -> None:
    # A suppressed HIGH finding overlapping a legitimate LOW finding at the same
    # span: pre-merge suppression keeps the legitimate one alive (the post-merge
    # hazard D5 guards against — HIGH would win the overlap then be dropped).
    stub = _StubScanner(
        (
            _pii("petasos.presidio.location", start=0, end=5, severity=Severity.HIGH),
            _pii("petasos.presidio.email_address", start=0, end=5, severity=Severity.LOW),
        )
    )
    p = Pipeline(scanners=[stub])
    result = asyncio.run(
        p.inspect("hello", profile={"suppress_rules": ["petasos.presidio.location"]})
    )
    rule_ids = {f.rule_id for f in result.findings}
    assert "petasos.presidio.email_address" in rule_ids  # legitimate survives
    assert "petasos.presidio.location" not in rule_ids  # suppressed


# ---------------------------------------------------------------------------
# D7 — config.pii_entities anonymize-stage filter
# ---------------------------------------------------------------------------

# text:  "email a@b.co ssn 111-22-3333"
#         0123456789...                 email span [6,12], ssn span [17,28]
_D7_TEXT = "email a@b.co ssn 111-22-3333"


def _email_and_ssn() -> tuple[ScanFinding, ...]:
    return (
        _pii(
            "petasos.presidio.email_address",
            start=6,
            end=12,
            matched="a@b.co",
            severity=Severity.HIGH,
        ),
        _pii(
            "petasos.presidio.us_ssn",
            start=17,
            end=28,
            matched="111-22-3333",
            severity=Severity.CRITICAL,
        ),
    )


def test_pii_entities_filters_anonymize_set() -> None:
    cfg = PetasosConfig(anonymize=True, redaction_mode="replace", pii_entities=("EMAIL_ADDRESS",))
    p = Pipeline(scanners=[_StubScanner(_email_and_ssn())], config=cfg)
    result = asyncio.run(p.inspect(_D7_TEXT))
    assert result.sanitized_content is not None
    assert "a@b.co" not in result.sanitized_content  # email anonymized
    assert "111-22-3333" in result.sanitized_content  # SSN left unredacted (coverage cut)


def test_pii_entities_empty_anonymizes_all() -> None:
    cfg = PetasosConfig(anonymize=True, redaction_mode="replace", pii_entities=())
    p = Pipeline(scanners=[_StubScanner(_email_and_ssn())], config=cfg)
    result = asyncio.run(p.inspect(_D7_TEXT))
    assert result.sanitized_content is not None
    assert "a@b.co" not in result.sanitized_content
    assert "111-22-3333" not in result.sanitized_content  # back-compat: anonymize all


def test_pii_entities_excludes_all_skips_anonymize() -> None:
    cfg = PetasosConfig(anonymize=True, redaction_mode="replace", pii_entities=("CRYPTO",))
    p = Pipeline(scanners=[_StubScanner(_email_and_ssn())], config=cfg)
    result = asyncio.run(p.inspect(_D7_TEXT))
    # no finding matches the filter -> anonymize skipped -> sanitized stays None
    assert result.sanitized_content is None


@requires_presidio_libs
def test_pii_entities_filter_hash_mode() -> None:
    cfg = PetasosConfig(
        anonymize=True,
        redaction_mode="hash",
        hash_key="test-key",
        pii_entities=("EMAIL_ADDRESS",),
    )
    p = Pipeline(scanners=[_StubScanner(_email_and_ssn())], config=cfg)
    result = asyncio.run(p.inspect(_D7_TEXT))
    assert result.sanitized_content is not None
    assert "a@b.co" not in result.sanitized_content  # email hashed (engine path)
    # non-vacuous: the SSN appears in cleartext (Stage 9 ran, but filtered it out)
    assert "111-22-3333" in result.sanitized_content
