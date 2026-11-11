"""Check raw payload size, control bytes, and JSON depth."""

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

# --- Structural checks ---

_BINARY_PATTERN = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")


def _check_structural(self: MinimalScanner, text: str, findings: list[ScanFinding]) -> None:
    # Oversized payload
    payload_size = len(text.encode("utf-8"))
    if payload_size > self._max_payload_bytes:
        findings.append(
            ScanFinding(
                rule_id="petasos.syntactic.structural.oversized-payload",
                finding_type="structural",
                severity=Severity.CRITICAL,
                confidence=1.0,
                message=(
                    f"Payload size {payload_size} bytes exceeds limit {self._max_payload_bytes}"
                ),
                scanner_name=self.name,
            )
        )

    # Binary content
    m = _BINARY_PATTERN.search(text)
    if m:
        findings.append(
            ScanFinding(
                rule_id="petasos.syntactic.structural.binary-content",
                finding_type="structural",
                severity=Severity.CRITICAL,
                confidence=1.0,
                message="Binary control characters detected in input",
                scanner_name=self.name,
                position=Position(start=m.start(), end=m.end()),
                matched_text=repr(m.group()),
            )
        )

    # Excessive JSON depth (iterative bracket counting)
    max_depth = self._check_json_depth(text)
    if max_depth > self._max_json_depth:
        findings.append(
            ScanFinding(
                rule_id="petasos.syntactic.structural.excessive-depth",
                finding_type="structural",
                severity=Severity.CRITICAL,
                confidence=1.0,
                message=f"JSON nesting depth {max_depth} exceeds limit {self._max_json_depth}",
                scanner_name=self.name,
            )
        )


def _check_json_depth(self: MinimalScanner, text: str) -> int:
    depth = 0
    max_depth = 0
    has_brackets = False
    in_string = False
    prev_backslash = False
    for ch in text:
        if in_string:
            if ch == '"' and not prev_backslash:
                in_string = False
            prev_backslash = ch == "\\" and not prev_backslash
            continue
        if ch == '"':
            in_string = True
            prev_backslash = False
            continue
        if ch in ("{", "["):
            has_brackets = True
            depth += 1
            if depth > max_depth:
                max_depth = depth
        elif ch in ("}", "]") and depth > 0:
            depth -= 1
    if not has_brackets:
        return 0
    return max_depth
