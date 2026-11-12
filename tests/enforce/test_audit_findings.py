"""Pin privacy-safe per-finding audit records from enforcer handlers.

See docs/architecture/rationale.md, "Alert and audit test constraints"."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
from petasos.enforce.engine import _audit
from petasos.model import PipelineResult, ScanFinding, Severity
from petasos.session.audit import AuditEmitter

if TYPE_CHECKING:
    import pytest

_LOGGER = "petasos.enforce.audit_findings"


def _finding(
    rule_id: str,
    severity: Severity,
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


def _lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("PETASOS_AUDIT_FINDING")
    ]


def test_emit_findings_writes_one_line_per_finding(caplog: pytest.LogCaptureFixture) -> None:
    """Pin emit findings writes one line per finding."""
    config = from_mapping(PetasosConfig, {"audit": {"emit_findings": True}})
    emitter = AuditEmitter(config, on_audit=_audit(logging.getLogger(_LOGGER)))
    blocking = _finding("minimal.injection.override", Severity.HIGH)
    quiet = _finding("minimal.role.suspicious", Severity.LOW, 0.3)
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        event = emitter.emit(
            PipelineResult(safe=False, findings=(blocking, quiet)),
            "s1",
            None,
        )
    assert isinstance(event.payload["findings"], list)
    lines = _lines(caplog)
    assert len(lines) == 2
    joined = "\n".join(lines)
    assert "rule_id=minimal.injection.override" in joined
    assert "rule_id=minimal.role.suspicious" in joined
    assert "severity=high" in joined
    assert "severity=low" in joined
    for line in lines:
        for key in ("rule_id=", "severity=", "confidence=", "direction="):
            assert key in line


def test_a_safe_result_is_still_recorded_when_the_toggle_is_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Pin a safe result is still recorded when the toggle is on."""
    config = from_mapping(PetasosConfig, {"audit": {"emit_findings": True}})
    emitter = AuditEmitter(config, on_audit=_audit(logging.getLogger(_LOGGER)))
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        emitter.emit(
            PipelineResult(
                safe=True,
                findings=(_finding("minimal.encoding.base64", Severity.MEDIUM),),
            ),
            "s1",
            None,
        )
    lines = _lines(caplog)
    assert len(lines) == 1
    assert "rule_id=minimal.encoding.base64" in lines[0]


def test_findings_are_not_logged_unless_the_toggle_is_on(caplog: pytest.LogCaptureFixture) -> None:
    """Pin findings are not logged unless the toggle is on."""
    emitter = AuditEmitter(PetasosConfig(), on_audit=_audit(logging.getLogger(_LOGGER)))
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        emitter.emit(
            PipelineResult(
                safe=False,
                findings=(_finding("minimal.injection.override", Severity.HIGH),),
            ),
            "s1",
            None,
        )
    assert _lines(caplog) == []
    assert any(record.getMessage().startswith("PETASOS_AUDIT ") for record in caplog.records)
