"""Report encoding signals and injection co-occurrence."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from petasos.scanners.minimal.scanner import MinimalScanner


import re

from petasos.model import (
    Position,
    ScanFinding,
    Severity,
)

# --- Encoding detection ---

_BASE64_PATTERN = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")


def _check_encoding(
    self: MinimalScanner,
    raw_text: str,
    normalized: object,
    findings: list[ScanFinding],
) -> None:
    from petasos.model import NormalizedText as _NT

    assert isinstance(normalized, _NT)

    # Invisible chars
    invis_rule = "petasos.syntactic.encoding.invisible-chars"
    if invis_rule not in self._suppress_rules and normalized.invisible_chars_stripped > 0:
        findings.append(
            ScanFinding(
                rule_id=invis_rule,
                finding_type="encoding",
                severity=Severity.MEDIUM,
                confidence=1.0,
                message=(f"{normalized.invisible_chars_stripped} invisible character(s) stripped"),
                scanner_name=self.name,
            )
        )

    # Base64 — uses raw input
    b64_rule = "petasos.syntactic.encoding.base64-in-text"
    if b64_rule not in self._suppress_rules:
        m = _BASE64_PATTERN.search(raw_text)
        if m:
            findings.append(
                ScanFinding(
                    rule_id=b64_rule,
                    finding_type="encoding",
                    severity=Severity.LOW,
                    confidence=0.7,
                    message="Base64-encoded block detected in text",
                    scanner_name=self.name,
                    position=Position(start=m.start(), end=m.end()),
                    matched_text=m.group()[:50],
                )
            )

    # Homoglyph substitution (unconditional per D6 — fires without injection)
    homo_rule = "petasos.syntactic.encoding.homoglyph-substitution"
    if (
        homo_rule not in self._suppress_rules
        and "homoglyph_mapped" in normalized.transformations_applied
    ):
        findings.append(
            ScanFinding(
                rule_id=homo_rule,
                finding_type="encoding",
                severity=Severity.LOW,
                confidence=1.0,
                message="Confusable character substitution detected",
                scanner_name=self.name,
            )
        )

    # RTL override
    rtl_rule = "petasos.syntactic.encoding.rtl-override"
    if rtl_rule not in self._suppress_rules and normalized.rtl_overrides_detected:
        findings.append(
            ScanFinding(
                rule_id=rtl_rule,
                finding_type="encoding",
                severity=Severity.MEDIUM,
                confidence=1.0,
                message="RTL override character detected",
                scanner_name=self.name,
            )
        )


def _apply_escalation(
    self: MinimalScanner, findings: list[ScanFinding], injection_matched: bool
) -> None:
    if not injection_matched:
        return

    invis_rule = "petasos.syntactic.encoding.invisible-chars"
    for i, f in enumerate(findings):
        if f.rule_id == invis_rule and f.severity == Severity.MEDIUM:
            findings[i] = ScanFinding(
                rule_id=f.rule_id,
                finding_type=f.finding_type,
                severity=Severity.HIGH,
                confidence=f.confidence,
                message=f.message + " (escalated: co-occurs with injection)",
                scanner_name=f.scanner_name,
                position=f.position,
                matched_text=f.matched_text,
            )
