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

from petasos.model import (
    NormalizedText,
    Position,
    ScanFinding,
    Severity,
)

# --- Agent-directed fetch/install directive (PET-154) ---
#
# Compositional injection-class detector (Decisions D1/D2/DS1-DS3): a finding
# requires an agent-address MARKER (factor 1) co-occurring with a fetch/install/
# execute ACTION (factor 2) and an external-RESOURCE cue (factor 3), all within a
# single physical line. The marker is the precision lever — a README describes an
# install; it does not address the agent. Direction-blind, unsuppressible, HIGH
# (never CRITICAL). Patterns run on canonical normalized text plus
# separator/composed views (PET-201; same NormalizedText as _check_injection),
# so homoglyph/invisible-char obfuscation is already unwound, and via the
# PET-98 rescan path for decoded carriers. Final patterns refined
# against AGENT_DIRECTIVE_BENIGN per PET-93 widen-then-retreat.

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

# WEAK speaker-tag markers (Decision DS4) — `Assistant:`/`Agent:` prefix vast
# amounts of benign transcript, so they pair ONLY with the high-danger
# archive/exec resource class (not a bare document URL). No re.MULTILINE: the
# per-line helper applies them to one physical line, where `^` already anchors
# the line start.
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

# Archive/executable extension sub-class (the high-danger resource cue). The
# Windows-native droppers (.ps1/.bat/.cmd/.scr) and common archives
# (.7z/.gz/.bz2/.xz) are included alongside the Unix set (PET-154 round-3
# edge-cases F-1: Windows is a first-class consumer; the speaker-tag form is the
# only path gated on this list and would otherwise miss `…/x.ps1`).
_AGENT_DIRECTIVE_ARCHIVE = re.compile(
    r"\.(?:zip|sh|exe|whl|tar\.gz|tgz|gz|bz2|xz|7z|deb|rpm|msi|dmg|pkg|jar"
    r"|ps1|bat|cmd|scr)\b",
    re.IGNORECASE,
)

# Full resource set: URL/SCP scheme OR archive/exec extension.
_AGENT_DIRECTIVE_RESOURCES: list[re.Pattern[str]] = [
    re.compile(r"https?://|ftp://|git://|\bgit@\S", re.IGNORECASE),
    _AGENT_DIRECTIVE_ARCHIVE,
]

# Cheap necessary-condition gate (Decision D4, mirroring _INJECTION_ANCHOR /
# _COMMAND_ANCHOR). KEYWORD-substring superset of every _AGENT_DIRECTIVE_MARKERS
# literal: each marker's mandatory noun keyword (agent / assistant / instruction
# / model / llm / ai) is an anchor alternative, so a candidate matching none
# cannot match any marker and skips the conjunction. `\bai\b` is word-bounded so
# it prunes (the standalone word "AI" is rare; it does not match "email"/"again")
# while keeping the `(?:...|AI)` trailing-noun branch of the if-you-are-an marker
# sound regardless of the `a`/`an` determiner. No phrase branches — every marker
# is covered by a single keyword, so the anchor is a genuine substring superset.
# MUST remain a keyword superset if a marker is added/widened —
# test_agent_directive_anchor_is_sound pins per-marker-branch reachability (every
# trailing-noun alternative, determiner-minimized).
_AGENT_DIRECTIVE_ANCHOR = re.compile(
    r"agent|assistant|instruction|\bmodel\b|\bllm\b|\bai\b",
    re.IGNORECASE,
)


def _first_match(patterns: list[re.Pattern[str]], text: str) -> re.Match[str] | None:
    for pat in patterns:
        m = pat.search(text)
        if m is not None:
            return m
    return None


def _agent_directive_line_hit(text: str) -> tuple[int, int] | None:
    """Per-line marker × action × resource conjunction (PET-154, Decisions DS3/DS4).

    Returns the **absolute** ``(start, end)`` of the marker on the first
    satisfying line, else ``None``. At most one hit per call (no ``finditer``) —
    the one-finding-per-scan invariant that bounds the rule's frequency-weight
    (10.0) contribution to a single increment (D3/§D).
    """
    # Whole-text anchor pre-gate first (Decision D4): no marker keyword anywhere
    # -> skip entirely (the no-match fast path holding the <5ms budget).
    if not _AGENT_DIRECTIVE_ANCHOR.search(text):
        return None
    # Per-line conjunction (Decision DS3). Split on "\n" ONLY — NOT
    # str.splitlines(), whose boundary set also includes \r, \v, \f, \x1c-\x1e,
    # \x85, U+2028, U+2029. Those code points survive normalize() (none is
    # Cf/INVISIBLE_NON_CF; NFKC leaves them intact), so a splitlines()-based loop
    # would let a single U+2028 between the marker and the resource split the
    # conjunction and silently evade the rule. With a "\n"-only split those
    # characters stay in-line and the conjunction fires; real "\n"/"\r\n"
    # transcripts still split (a lone trailing "\r" is harmless). `+ 1` per
    # iteration accounts for the "\n" that split() removed, keeping offsets
    # absolute into ``text``.
    offset = 0
    for line in text.split("\n"):
        if _first_match(_AGENT_DIRECTIVE_ACTIONS, line) is not None:
            # STRONG directed-at marker pairs with ANY external resource.
            strong = _first_match(_AGENT_DIRECTIVE_MARKERS, line)
            if strong is not None and _first_match(_AGENT_DIRECTIVE_RESOURCES, line) is not None:
                return offset + strong.start(), offset + strong.end()
            # WEAK speaker-tag marker (DS4) requires the archive/exec resource
            # class — a bare document URL (.pdf, a webpage) is not enough.
            tag = _first_match(_AGENT_DIRECTIVE_SPEAKER_TAG, line)
            if tag is not None and _AGENT_DIRECTIVE_ARCHIVE.search(line) is not None:
                return offset + tag.start(), offset + tag.end()
        offset += len(line) + 1
    return None


def _check_agent_directive(
    self: MinimalScanner, normalized: NormalizedText, findings: list[ScanFinding]
) -> bool:
    # PET-154: agent-address marker × fetch/install/execute action × external
    # resource, per physical line (the _agent_directive_line_hit conjunction).
    # The suppress check is omitted because the rule_id is stripped from
    # _suppress_rules at construction (Decision D1) — same idiom as the rescan
    # injection battery. At most one finding per scan (Decision DS3).
    # Canonical first, then separator extras only (PET-211). Composed
    # extras are not searched. Omit span on extras.
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
    # One-finding-per-scan invariant (DS3): the agent-directive rule's 10.0
    # frequency weight is only safe if a single scan emits at most ONE such
    # finding — five would reach the 50.0 Tier-3 floor and terminate a session
    # from a single payload. The plain path (Step 4c, which runs before this
    # decode path) is self-bounded (the per-line helper returns one hit), but
    # the decode-and-rescan path runs once PER decoded candidate, so N repeated
    # base64/hex carriers of the same directive would otherwise emit N findings.
    # Cap to one surviving agent-directive finding across the plain path and all
    # decoded candidates. Pinned by test_tier3_safety_decoded_carriers_one_finding.
    if any(f.rule_id in _AGENT_DIRECTIVE_RULE_IDS for f in findings):
        return False
    # PET-154 (Decision D6): rescan a decoded carrier for the agent-directive
    # conjunction. Resolution is inlined (not a call to _resolve_finding_shape)
    # because the per-line helper returns absolute (start, end) offsets rather
    # than a re.Match — a blob candidate reports the fixed raw-space blob span;
    # the ROT13 view resolves per-match in normalized space, where the absolute
    # offsets index validly into cand.origin_text because ROT13 is
    # length-preserving.
    # Blob candidates carry RAW decoded text (scan_text=decoded above), so a
    # base64/hex-wrapped directive with a zero-width char inside `install` or a
    # homoglyph in the marker would evade what the normalized plain path
    # catches. Search concat first (reuse the NormalizedText from
    # _rescan_candidate), then unique separator extras. Composed extras
    # are not appended. The finding
    # reports the fixed carrier span (cand.position/.matched_text), so detecting
    # on a normalized view does not disturb offset mapping. The ROT13 branch
    # must stay raw as the primary — its hit offsets index 1:1 into origin_text
    # and NFKC would desync them (origin_text is itself normalized-space).
    primary = nt.normalized if cand.position is not None else cand.scan_text
    texts = (primary, *_separator_extras(primary, nt))
    for idx, scan_text in enumerate(texts):
        hit = _agent_directive_line_hit(scan_text)
        if hit is None:
            continue
        start, end = hit
        extra = idx > 0
        if cand.position is not None:  # blob candidate: fixed raw-space blob span
            assert cand.matched_text is not None
            position: Position | None = cand.position
            matched_text: str | None = cand.matched_text
        elif extra:
            position = None
            matched_text = None
        else:  # ROT13 view: per-match in normalized space (offsets map 1:1)
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
