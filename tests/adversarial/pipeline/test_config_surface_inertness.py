"""PET-169 test-8 inertness arms: the `live-shim` keys move no library outcome.

Five keys the 2026-08-03 config-surface honesty audit newly classified
`live-shim` are pinned here. Each is rendered as an operator control in the
Config Editor, and each is inert for a program that imports `petasos` and drives
`Pipeline` itself. That is an inertness claim, and PET-143 D-A says an inertness
claim is discharged by an outcome diff, not by a code trace:

    verify each toggle moves a detection *outcome* (an on/off diff test) before
    treating it as a live control; if it cannot, retire the surface

`init_wait_timeout_seconds` is the sixth `live-shim` key and is grandfathered by
PET-167, which already disclosed its scope.

**Every arm carries a positive control.** Without one, "two PipelineResults are
equal" is true of all 64 config fields and pins nothing. The control is a stub
Scanner emitting positioned `finding_type="pii"` findings plus `anonymize=True`
and an extras-free `redaction_mode`, so `sanitized_content` is non-None on both
arms: the pipeline demonstrably reaches the anonymization stage while the flipped
key moves nothing. The stub is necessary because `MinimalScanner` emits only
injection/command/encoding/structural findings, so the PII filter would otherwise
be empty and the whole stage unreachable.

The comparison is over the serialized `PipelineResult`, excluding only the
run-to-run wall-clock `duration_ms`, following the shipped PET-151 idiom at
`tests/adversarial/normalization/test_unicode_bypass.py:347`. Each arm builds
fresh pipelines with no shared session, which keeps `session_score` and
`escalation_tier` from diverging for a reason unrelated to the toggle.
"""

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
        return "pii-stub"

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
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
        # Presidio detection scope. Pipeline never constructs a PresidioScanner;
        # it fans out over the scanners the caller supplied. An embedder who
        # passes their own scanner still gets nothing from these three.
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
        # Egress-fence keys. Their behavior reads are the host's; a library
        # Pipeline that is handed its scanners does not consult them.
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
    """Regression for PET-169: flipping a `live-shim` key changes nothing a
    library embedder's Pipeline produces. A future change that threads any of
    these into `petasos/` reds this and owes the verdict a re-classification."""
    on = await _pipeline(on_overrides).inspect(_TEXT, direction="inbound")
    off = await _pipeline(off_overrides).inspect(_TEXT, direction="inbound")

    # Positive control: the run reached the anonymization stage under BOTH arms,
    # so the equality below is a real comparison and not a vacuous one.
    for arm, result in (("on", on), ("off", off)):
        assert result.sanitized_content is not None, f"{arm} arm never reached anonymization"
        assert "<PERSON_1>" in result.sanitized_content, f"{arm} arm anonymized nothing"
        assert not any("presidio not installed" in e for e in result.errors), (
            f"{arm} arm took the ImportError path, so it pins the handler not the key"
        )

    assert _reduce(on) == _reduce(off)
