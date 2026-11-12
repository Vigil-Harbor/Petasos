"""Recognize destructive and obfuscated outbound commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from petasos.scanners.minimal.views import _family_search_views

if TYPE_CHECKING:
    from petasos.scanners.minimal.scanner import MinimalScanner


import re

from petasos.model import (
    NormalizedText,
    Position,
    ScanFinding,
    Severity,
)

# See docs/architecture/rationale.md, "Command detection boundaries".
_COMMAND_PATTERNS: list[tuple[str, re.Pattern[str], float]] = [
    (
        # See docs/architecture/rationale.md, "Command detection boundaries".
        "pipe-to-shell",
        re.compile(r"\|\s*(?:sudo\s+(?:-\S+\s+)*)?(?:ba|z|da)?sh\b(?!\s*[\|)])"),
        0.7,
    ),
    (
        # See docs/architecture/rationale.md, "Command detection boundaries".
        "decode-exec",
        re.compile(
            r"\b(?:base64\s+(?:-d|-D|--decode)|xxd\s+-r(?:\s+-p)?|openssl\s+enc\s+-d)"
            r"[^|\n]*\|\s*(?:sudo\s+(?:-\S+\s+)*)?(?:ba|z|da)?sh\b(?!\s*\|)"
        ),
        0.9,
    ),
    (
        # See docs/architecture/rationale.md, "Command detection boundaries".
        "fetch-exec",
        re.compile(
            r"\b(?:curl|wget)\b[^|\n]*\|\s*(?:sudo\s+(?:-\S+\s+)*)?(?:ba|z|da)?sh\b(?!\s*\|)"
        ),
        0.9,
    ),
    (
        # See docs/architecture/rationale.md, "Command detection boundaries".
        "alias-escape",
        re.compile(r"\\(?:rm|mv|dd|chmod|chown|mkfs|shred)\s+(?:-[a-zA-Z]|/|~|[0-7]{3,4}\b)"),
        0.9,
    ),
    (
        # See docs/architecture/rationale.md, "Command detection boundaries".
        "destructive-recursive",
        re.compile(
            r"\brm\s+(?:-[a-zA-Z]+\s+)*-[a-zA-Z]*(?:[rR][fF]|[fF][rR])[a-zA-Z]*\s+"
            r"""["']?(?:/|~|\$\{?HOME\b\}?|--no-preserve-root)"""
            r"|\bdd\b[^|\n]*\bof=/dev/(?!null\b|std(?:out|err)\b|zero\b|shm/)"
            r"|\bmkfs\.[a-z0-9]+\s+(?:-[a-zA-Z]|/dev/)"
        ),
        0.95,
    ),
]

# See docs/architecture/rationale.md, "Syntactic anchor soundness".
_COMMAND_ANCHOR = re.compile(
    r"sh|base64|xxd|openssl|curl|wget|rm|dd|mkfs|chmod|chown|shred|mv|\\",
    re.IGNORECASE,
)


def _check_command(
    self: MinimalScanner, normalized: NormalizedText, findings: list[ScanFinding]
) -> None:
    # See docs/architecture/rationale.md, "Syntactic anchor soundness".
    views = _family_search_views(normalized)
    if not any(_COMMAND_ANCHOR.search(v) for v in views):
        return
    for slug, pattern, confidence in _COMMAND_PATTERNS:
        rule_id = f"petasos.syntactic.command.{slug}"
        if rule_id in self._suppress_rules:
            continue
        # See docs/architecture/rationale.md, "Command detection boundaries".
        for idx, text in enumerate(views):
            if not _COMMAND_ANCHOR.search(text):
                continue
            m = pattern.search(text)
            if m is None:
                continue
            if idx == 0:
                position: Position | None = Position(start=m.start(), end=m.end())
                # Cap: bounded `[^|\n]*` runs make m.group() attacker-
                # inflatable (cf. the base64-in-text [:50] cap).
                matched_text: str | None = text[m.start() : m.end()][:120]
            else:
                position = None
                matched_text = None
            findings.append(
                ScanFinding(
                    rule_id=rule_id,
                    finding_type="command",
                    severity=Severity.HIGH,
                    confidence=confidence,
                    message=f"Obfuscated/destructive command pattern matched: {slug}",
                    scanner_name=self.name,
                    position=position,
                    matched_text=matched_text,
                )
            )
            break
