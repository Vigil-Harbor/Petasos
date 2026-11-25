"""Recognize instruction-override patterns."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from petasos.scanners.minimal.scanner import MinimalScanner


import re

from petasos.model import (
    NormalizedText,
    Position,
    ScanFinding,
    Severity,
)

# See docs/architecture/rationale.md, "Injection pattern precision".

_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "ignore-previous",
        # Determiner stacks keep multi-determiner instructions within detection.
        re.compile(
            r"ignore\s+(?:(?:all|any|your|the|my|of|these|those)\s+){0,3}"
            r"(?:previous|prior|above|earlier|preceding)\s+instructions",
            re.IGNORECASE,
        ),
    ),
    (
        "ignore-all",
        re.compile(
            r"ignore\s+(?:all|any)\s+(?:(?:of\s+)?(?:the|your|my|these|those)\s+)?instructions",
            re.IGNORECASE,
        ),
    ),
    (
        "disregard",
        re.compile(
            r"(?:disregard|forget)\s+(?:(?:all|any|your|the|my|of|these|those)\s+){0,3}"
            r"(?:previous|prior|above|earlier|preceding)\s+instructions"
            r"|(?:disregard|forget)\s+(?:all|any)\s+(?:(?:of\s+)?(?:the|your|my|these|those)\s+)?instructions"
            r"|disregard\s+your",
            re.IGNORECASE,
        ),
    ),
    ("you-are-now", re.compile(r"you(?:\s+are|['’ʼ]re)\s+now", re.IGNORECASE)),
    (
        "new-instructions",
        # The determiner "the" also introduces benign README instructions.
        re.compile(
            r"your\s+new\s+instructions\s+are\b|new\s+instructions\s*:",
            re.IGNORECASE,
        ),
    ),
    (
        "system-override",
        re.compile(r"system\s+override|override\s+(?:the\s+)?system\s+prompt", re.IGNORECASE),
    ),
    # [ \t] (not \s) is load-bearing: \s* under MULTILINE backtracks
    # quadratically across newline floods and would match indented YAML keys.
    ("system-prefix", re.compile(r"^SYSTEM[ \t]*:", re.MULTILINE | re.IGNORECASE)),
    ("inst-delimiter", re.compile(r"\[/?INST\]|</?INST>|<</?SYS>>", re.IGNORECASE)),
]


# See docs/architecture/rationale.md, "Syntactic anchor soundness".
_INJECTION_ANCHOR = re.compile(r"inst|sys|disregard|now", re.IGNORECASE)


def _check_injection(
    self: MinimalScanner, normalized: NormalizedText, findings: list[ScanFinding]
) -> bool:
    # See docs/architecture/rationale.md, "Decoded coordinate spaces".
    raw_candidates: list[tuple[str, str]] = [(normalized.normalized, "plain")]
    raw_candidates.extend((v, "leet") for v in normalized.leet_views)
    raw_candidates.extend((v, "separator") for v in normalized.separator_views)
    raw_candidates.extend((v, "composed") for v in normalized.composed_views)
    candidates = [c for c in raw_candidates if _INJECTION_ANCHOR.search(c[0])]
    if not candidates:
        return False
    any_matched = False
    for slug, pattern in _INJECTION_PATTERNS:
        rule_id = f"petasos.syntactic.injection.{slug}"
        if rule_id in self._suppress_rules:
            continue
        for text, kind in candidates:
            m = pattern.search(text)
            if m is None:
                continue
            any_matched = True
            # Truncated: \s+ runs make m.group() attacker-inflatable
            # (cf. the base64-in-text [:50] cap).
            decoded = f" (leet-decoded: {m.group()[:80]!r})" if kind == "leet" else ""
            if kind in ("separator", "composed"):
                position = None
                matched_text = None
            else:
                position = Position(start=m.start(), end=m.end())
                matched_text = normalized.normalized[m.start() : m.end()]
            findings.append(
                ScanFinding(
                    rule_id=rule_id,
                    finding_type="injection",
                    severity=Severity.HIGH,
                    confidence=1.0,
                    message=f"Injection pattern matched: {slug}{decoded}",
                    scanner_name=self.name,
                    position=position,
                    matched_text=matched_text,
                )
            )
            break
    return any_matched
