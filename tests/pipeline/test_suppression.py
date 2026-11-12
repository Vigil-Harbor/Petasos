"""Pin pre-merge suppression and protected severity floors across scanners.

See docs/architecture/rationale.md, "Finding suppression floors"."""

from __future__ import annotations

import asyncio

import pytest

from petasos.config.schema import ConfigError, from_mapping
from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig
from petasos.model import Direction, Position, ScanFinding, ScanResult, Severity
from petasos.pipeline import Pipeline
from petasos.pipeline.findings import _is_floor_rule, _suppress_scanner_findings

_INJECTION_ID = "petasos.syntactic.injection.role-switch-capability"

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
        """Return the fixture scanner name."""
        return self._name

    async def scan(
        self, text: str, *, direction: Direction = "inbound", session_id: str | None = None
    ) -> ScanResult:
        """Supply the configured scanner response for this fixture."""
        return ScanResult(scanner_name=self._name, findings=self._findings, duration_ms=0.0)


def test_profile_suppresses_presidio_finding_end_to_end() -> None:
    """Pin profile suppresses presidio finding end to end."""
    findings = (_pii("petasos.presidio.location", start=0, end=5),)
    suppressed = Pipeline(
        scanners=[_StubScanner(findings)],
        config=from_mapping(
            PetasosConfig,
            {"rules": {"suppress": ["petasos.presidio.location"]}},
        ),
    )
    result = asyncio.run(suppressed.inspect("hello world"))
    assert not any(f.rule_id == "petasos.presidio.location" for f in result.findings)
    plain = asyncio.run(Pipeline(scanners=[_StubScanner(findings)]).inspect("hello world"))
    assert any(f.rule_id == "petasos.presidio.location" for f in plain.findings)


def test_suppress_cannot_silence_injection_or_structural() -> None:
    """Pin suppress cannot silence injection or structural."""
    with pytest.raises(ConfigError, match="rules.suppress"):
        from_mapping(PetasosConfig, {"rules": {"suppress": [_INJECTION_ID]}})


def test_suppress_helper_honors_floor_directly() -> None:
    """Pin suppress helper honors floor directly."""
    results = [ScanResult(scanner_name="stub", findings=(_injection(),), duration_ms=0.0)]
    out = _suppress_scanner_findings(results, frozenset({_INJECTION_ID}))
    assert _is_floor_rule(_INJECTION_ID) is True
    assert len(out[0].findings) == 1
    assert out[0].findings[0].rule_id == _INJECTION_ID


def test_severity_override_can_downgrade_pii() -> None:
    """Pin severity override can downgrade pii."""
    stub = _StubScanner(
        (
            _pii("petasos.presidio.person", start=0, end=5, severity=Severity.MEDIUM),
            _injection(start=10, end=20),
        )
    )
    p = Pipeline(
        scanners=[stub],
        config=from_mapping(
            PetasosConfig,
            {
                "rules": {
                    "severity_overrides": {
                        "petasos.presidio.person": "info",
                        _INJECTION_ID: "info",
                    }
                }
            },
        ),
    )
    result = asyncio.run(p.inspect("name here payload here"))
    by_rule = {f.rule_id: f for f in result.findings}
    assert by_rule["petasos.presidio.person"].severity == Severity.INFO
    assert by_rule[_INJECTION_ID].severity == Severity.HIGH


def test_suppressed_finding_does_not_escalate() -> None:
    """Pin suppressed finding does not escalate."""
    crits = tuple(
        _pii("petasos.presidio.location", start=i, end=i + 3, severity=Severity.CRITICAL)
        for i in (0, 4, 8)
    )
    control = asyncio.run(
        Pipeline(scanners=[_StubScanner(crits)]).inspect("abcdefghijkl", session_id="s1")
    )
    assert control.escalation_tier == "tier3"
    assert control.safe is False

    suppressed = asyncio.run(
        Pipeline(
            scanners=[_StubScanner(crits)],
            config=from_mapping(
                PetasosConfig,
                {"rules": {"suppress": ["petasos.presidio.location"]}},
            ),
        ).inspect("abcdefghijkl", session_id="s2")
    )
    assert suppressed.findings == ()
    assert suppressed.escalation_tier != "tier3"


def test_suppressed_overlap_does_not_evict_legitimate() -> None:
    """Pin suppressed overlap does not evict legitimate."""
    stub = _StubScanner(
        (
            _pii("petasos.presidio.location", start=0, end=5, severity=Severity.HIGH),
            _pii("petasos.presidio.email_address", start=0, end=5, severity=Severity.LOW),
        )
    )
    p = Pipeline(
        scanners=[stub],
        config=from_mapping(
            PetasosConfig,
            {"rules": {"suppress": ["petasos.presidio.location"]}},
        ),
    )
    result = asyncio.run(p.inspect("hello"))
    rule_ids = {f.rule_id for f in result.findings}
    assert "petasos.presidio.email_address" in rule_ids
    assert "petasos.presidio.location" not in rule_ids


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
    """Pin pii entities filters anonymize set."""
    cfg = from_mapping(
        PetasosConfig,
        {
            "anonymization": {
                "enabled": True,
                "mode": "replace",
                "entities": ("EMAIL_ADDRESS",),
            },
        },
    )
    p = Pipeline(scanners=[_StubScanner(_email_and_ssn())], config=cfg)
    result = asyncio.run(p.inspect(_D7_TEXT))
    assert result.sanitized_content is not None
    assert "a@b.co" not in result.sanitized_content
    assert "111-22-3333" in result.sanitized_content


def test_pii_entities_empty_anonymizes_all() -> None:
    """Pin pii entities empty anonymizes all."""
    cfg = from_mapping(
        PetasosConfig,
        {
            "anonymization": {
                "enabled": True,
                "mode": "replace",
                "entities": (),
            },
        },
    )
    p = Pipeline(scanners=[_StubScanner(_email_and_ssn())], config=cfg)
    result = asyncio.run(p.inspect(_D7_TEXT))
    assert result.sanitized_content is not None
    assert "a@b.co" not in result.sanitized_content
    assert "111-22-3333" not in result.sanitized_content


def test_pii_entities_excludes_all_skips_anonymize() -> None:
    """Pin pii entities excludes all skips anonymize."""
    cfg = from_mapping(
        PetasosConfig,
        {
            "anonymization": {
                "enabled": True,
                "mode": "replace",
                "entities": ("CRYPTO",),
            },
        },
    )
    p = Pipeline(scanners=[_StubScanner(_email_and_ssn())], config=cfg)
    result = asyncio.run(p.inspect(_D7_TEXT))
    assert result.sanitized_content is None


@requires_presidio_libs
def test_pii_entities_filter_hash_mode() -> None:
    """Pin pii entities filter hash mode."""
    cfg = from_mapping(
        PetasosConfig,
        {
            "anonymization": {
                "enabled": True,
                "mode": "hash",
                "entities": ("EMAIL_ADDRESS",),
            }
        },
    )
    p = Pipeline(
        scanners=[_StubScanner(_email_and_ssn())],
        config=cfg,
        secrets=Secrets(hash_key="test-key"),
    )
    result = asyncio.run(p.inspect(_D7_TEXT))
    assert result.sanitized_content is not None
    assert "a@b.co" not in result.sanitized_content
    assert "111-22-3333" in result.sanitized_content
