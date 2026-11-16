"""Recognize agent-directed fetch and execution instructions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from petasos.scanners.minimal.taxonomy import _AGENT_DIRECTIVE_RULE_IDS
from petasos.scanners.minimal.views import (
    _DecodeCandidate,
    _family_search_views,
    _separator_extras,
)

if TYPE_CHECKING:
    from petasos.scanners.minimal.scanner import MinimalScanner


import re
from bisect import bisect_right

from petasos.model import (
    NormalizedText,
    Position,
    ScanFinding,
    Severity,
)

# See docs/architecture/rationale.md, "Agent directive boundaries".

# STRONG directed-at markers — rarely benign, so they pair with ANY external
# resource (URL scheme or archive/exec extension).
_AGENT_DIRECTIVE_MARKERS: list[re.Pattern[str]] = [
    re.compile(r"\bAI\s+agent\s+instruction", re.IGNORECASE),
    re.compile(
        r"\binstructions?\s+for\s+(?:the\s+)?(?:AI|assistant|agent|model|LLM)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bif\s+you(?:['’ʼ]re|\s+are)\s+an?\s+(?:AI|assistant|agent|model|LLM)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:to|for)\s+the\s+(?:assistant|agent|model|LLM)\b", re.IGNORECASE),
    re.compile(r"\b(?:AI|agent|assistant|system)\s+instruction\s*:", re.IGNORECASE),
]

# See docs/architecture/rationale.md, "Agent directive boundaries".
_AGENT_DIRECTIVE_SPEAKER_TAG: list[re.Pattern[str]] = [
    re.compile(r"^\s*assistant\s*:", re.IGNORECASE),
    re.compile(r"^\s*agent\s*:", re.IGNORECASE),
]

_AGENT_DIRECTIVE_ACTIONS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:download|install|fetch|execute|run)\b", re.IGNORECASE),
    re.compile(r"\b(?:pip|npm)\s+install\b", re.IGNORECASE),
    re.compile(r"\bgit\s+clone\b", re.IGNORECASE),
    re.compile(r"\b(?:curl|wget)\b", re.IGNORECASE),
]

# See docs/architecture/rationale.md, "Agent directive boundaries".
_AGENT_DIRECTIVE_ARCHIVE = re.compile(
    r"\.(?:zip|sh|exe|whl|tar\.gz|tgz|gz|bz2|xz|7z|deb|rpm|msi|dmg|pkg|jar"
    r"|ps1|bat|cmd|scr)\b",
    re.IGNORECASE,
)

_AGENT_DIRECTIVE_RESOURCES: list[re.Pattern[str]] = [
    re.compile(r"https?://|ftp://|git://|\bgit@\S", re.IGNORECASE),
    _AGENT_DIRECTIVE_ARCHIVE,
]

# See docs/architecture/rationale.md, "Syntactic anchor soundness".
_AGENT_DIRECTIVE_ANCHOR = re.compile(
    r"agent|assistant|instruction|\bmodel\b|\bllm\b|\bai\b",
    re.IGNORECASE,
)


# See docs/architecture/rationale.md, "Agent directive boundaries".
_AGENT_DIRECTIVE_REACH = 300


def _first_match(patterns: list[re.Pattern[str]], text: str) -> re.Match[str] | None:
    for pat in patterns:
        m = pat.search(text)
        if m is not None:
            return m
    return None


def _spans(patterns: list[re.Pattern[str]], text: str) -> list[tuple[int, int]]:
    return sorted(m.span() for pat in patterns for m in pat.finditer(text))


def _nearest(spans: list[tuple[int, int]], anchor: tuple[int, int]) -> list[tuple[int, int]]:
    """The span starting at or before ``anchor`` and the one starting after it."""
    at = bisect_right(spans, anchor)
    return spans[max(at - 1, 0) : at + 1]


def _together(
    anchors: list[tuple[int, int]],
    actions: list[tuple[int, int]],
    resources: list[tuple[int, int]],
) -> tuple[int, int] | None:
    """The first anchor with an action and a resource within reach of it.

    The three must fit inside ``_AGENT_DIRECTIVE_REACH`` characters. Only the
    neighbours on each side of an anchor can give the tightest fit.
    """
    for anchor in anchors:
        for action in _nearest(actions, anchor):
            for resource in _nearest(resources, anchor):
                low = min(anchor[0], action[0], resource[0])
                high = max(anchor[1], action[1], resource[1])
                if high - low <= _AGENT_DIRECTIVE_REACH:
                    return anchor
    return None


def _agent_directive_line_hit(text: str) -> tuple[int, int] | None:
    """Return the first marker with an action and a resource close by on its line."""
    if not _AGENT_DIRECTIVE_ANCHOR.search(text):
        return None
    # See docs/architecture/rationale.md, "Agent directive boundaries".
    offset = 0
    for line in text.split("\n"):
        if _first_match(_AGENT_DIRECTIVE_ACTIONS, line) is not None:
            actions = _spans(_AGENT_DIRECTIVE_ACTIONS, line)
            if _first_match(_AGENT_DIRECTIVE_MARKERS, line) is not None:
                hit = _together(
                    _spans(_AGENT_DIRECTIVE_MARKERS, line),
                    actions,
                    _spans(_AGENT_DIRECTIVE_RESOURCES, line),
                )
                if hit is not None:
                    return offset + hit[0], offset + hit[1]
            # Transcript speaker tags require an executable or archive resource.
            tag = _first_match(_AGENT_DIRECTIVE_SPEAKER_TAG, line)
            if tag is not None:
                hit = _together([tag.span()], actions, _spans([_AGENT_DIRECTIVE_ARCHIVE], line))
                if hit is not None:
                    return offset + hit[0], offset + hit[1]
        offset += len(line) + 1
    return None


def _check_agent_directive(
    self: MinimalScanner, normalized: NormalizedText, findings: list[ScanFinding]
) -> bool:
    # See docs/architecture/rationale.md, "Agent directive boundaries".
    for idx, text in enumerate(_family_search_views(normalized)):
        hit = _agent_directive_line_hit(text)
        if hit is None:
            continue
        start, end = hit
        if idx == 0:
            position: Position | None = Position(start=start, end=end)
            # Cap: marker patterns contain \s+ runs -> attacker-inflatable
            # group (cf. the base64-in-text [:50] cap).
            matched_text: str | None = text[start:end][:120]
        else:
            position = None
            matched_text = None
        findings.append(
            ScanFinding(
                rule_id="petasos.syntactic.injection.agent-directed-fetch",
                finding_type="injection",
                severity=Severity.HIGH,
                confidence=1.0,
                message="Agent-directed fetch/install directive detected",
                scanner_name=self.name,
                position=position,
                matched_text=matched_text,
            )
        )
        return True
    return False


def _rescan_agent_directive(
    self: MinimalScanner,
    cand: _DecodeCandidate,
    findings: list[ScanFinding],
    nt: NormalizedText,
) -> bool:
    # See docs/architecture/rationale.md, "Decoded finding budgets".
    if any(f.rule_id in _AGENT_DIRECTIVE_RULE_IDS for f in findings):
        return False
    # See docs/architecture/rationale.md, "Decoded coordinate spaces".
    primary = nt.normalized if cand.position is not None else cand.scan_text
    texts = (primary, *_separator_extras(primary, nt))
    for idx, scan_text in enumerate(texts):
        hit = _agent_directive_line_hit(scan_text)
        if hit is None:
            continue
        start, end = hit
        extra = idx > 0
        if cand.position is not None:
            assert cand.matched_text is not None
            position: Position | None = cand.position
            matched_text: str | None = cand.matched_text
        elif extra:
            position = None
            matched_text = None
        else:
            position = Position(start=start, end=end)
            matched_text = cand.origin_text[start:end]
        message = f"Agent-directed fetch/install directive detected ({cand.carrier}-decoded)"
        findings.append(
            ScanFinding(
                rule_id="petasos.syntactic.injection.agent-directed-fetch",
                finding_type="injection",
                severity=Severity.HIGH,
                confidence=1.0,
                message=message,
                scanner_name=self.name,
                position=position,
                matched_text=matched_text,
            )
        )
        return True
    return False
