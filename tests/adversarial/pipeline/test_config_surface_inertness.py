"""Pin library-inert controls with nonvacuous anonymization outcomes.

See docs/architecture/rationale.md, "Outcome-control fixtures"."""

from __future__ import annotations

from typing import Any

import pytest

from petasos.config.schema import from_mapping, merge
from petasos.config.sections import PetasosConfig
from petasos.model import (
    Direction,
    PipelineResult,
    Position,
    ScanFinding,
    ScanResult,
    Severity,
)
from petasos.pipeline import Pipeline

_TEXT = "Alice met alice@example.com today"


class _PiiStubScanner:
    """An ML scanner reporting two typed PII spans. Extras-free: it fabricates
    the findings a Presidio backend would produce, which is all the pipeline's
    anonymization stage consumes."""

    @property
    def name(self) -> str:
        """Return the fixture scanner name."""
        return "pii-stub"

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        """Supply the configured scanner response for this fixture."""
        findings = tuple(
            ScanFinding(
                rule_id=f"petasos.presidio.{entity.lower()}",
                finding_type="pii",
                severity=Severity.MEDIUM,
                confidence=0.9,
                message=f"PII detected: {entity}",
                scanner_name="pii-stub",
                position=Position(start=text.index(needle), end=text.index(needle) + len(needle)),
                matched_text=needle,
            )
            for needle, entity in (("Alice", "PERSON"), ("alice@example.com", "EMAIL_ADDRESS"))
            if needle in text
        )
        return ScanResult(scanner_name="pii-stub", findings=findings)


def _pipeline(overrides: dict[str, Any]) -> Pipeline:
    """A pipeline differing from the anonymizing baseline in exactly one field."""
    document = merge({"anonymization": {"enabled": True, "mode": "replace"}}, overrides)
    return Pipeline(scanners=[_PiiStubScanner()], config=from_mapping(PetasosConfig, document))


def _reduce(result: PipelineResult) -> dict[str, Any]:
    as_dict = result.to_dict()
    for scan_result in as_dict["scanner_results"]:
        scan_result.pop("duration_ms", None)
    return as_dict


@pytest.mark.parametrize(
    ("on_overrides", "off_overrides"),
    [
        # Caller-supplied scanners retain their own detection scope; the pipeline does not
        # reconstruct them.
        (
            {"scanners": {"presidio": {"entities": ["EMAIL_ADDRESS"]}}},
            {"scanners": {"presidio": {"entities": None}}},
        ),
        (
            {"scanners": {"presidio": {"entities_extra": ["URL"]}}},
            {"scanners": {"presidio": {"entities_extra": []}}},
        ),
        (
            {"scanners": {"presidio": {"score_threshold": 0.99}}},
            {"scanners": {"presidio": {"score_threshold": 0.01}}},
        ),
        (
            {"egress": {"sink_tools": ["send_email"]}},
            {"egress": {"sink_tools": []}},
        ),
        (
            {"egress": {"taint_namespaces": ["mcp_bank"]}},
            {"egress": {"taint_namespaces": []}},
        ),
    ],
    ids=[
        "presidio_entities",
        "presidio_entities_extra",
        "presidio_score_threshold",
        "egress_sink_tools",
        "source_taint_namespaces",
    ],
)
async def test_live_shim_key_moves_no_library_outcome(
    on_overrides: dict[str, Any], off_overrides: dict[str, Any]
) -> None:
    """Pin live shim key moves no library outcome."""
    on = await _pipeline(on_overrides).inspect(_TEXT, direction="inbound")
    off = await _pipeline(off_overrides).inspect(_TEXT, direction="inbound")

    for arm, result in (("on", on), ("off", off)):
        assert result.sanitized_content is not None, f"{arm} arm never reached anonymization"
        assert "<PERSON_1>" in result.sanitized_content, f"{arm} arm anonymized nothing"
        assert not any("presidio not installed" in e for e in result.errors), (
            f"{arm} arm took the ImportError path, so it pins the handler not the key"
        )

    assert _reduce(on) == _reduce(off)
