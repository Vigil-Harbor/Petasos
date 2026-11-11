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

# --- Injection patterns (8 rules) ---
#
# PET-93 phrasing audit verdicts (one line per rule; full rationale in
# docs/specs/TODO/PET-93.spec.md):
#   ignore-previous   WIDENED  determiner stack {0,3} + adjective synonyms
#                              (previous|prior|above|earlier|preceding).
#                              INTENTIONAL: paraphrase nouns ("ignore previous
#                              guidance"), bare "ignore the/your/these
#                              instructions" (benign-prose twin of disregard's
#                              bare form).
#   ignore-all        WIDENED  (all|any) + optional (of) determiner slot —
#                              catches the in-the-wild DAN opener "Ignore all
#                              the instructions you got before". Disjoint from
#                              ignore-previous by construction: no adjective
#                              slot here, adjective required there.
#   disregard         WIDENED  now the disregard/forget verb-class rule (verb
#                              partition keeps it disjoint from the ignore-*
#                              rules); adjective-required and all/any branches
#                              mirror the two ignore rules; legacy
#                              "disregard your" branch kept verbatim.
#                              INTENTIONAL: bare "disregard/forget the
#                              instructions" (common benign technical prose).
#   you-are-now       WIDENED  contraction branch (you're / curly / U+02BC).
#   new-instructions  WIDENED-THEN-RETREATED  "your new instructions are" +
#                              legacy colon form. The "(your|the)" variant was
#                              retreated to "your" only after the D6 benign
#                              corpus flagged "The new instructions are in the
#                              README" as a new FP (spec row 5's pre-committed
#                              fallback). INTENTIONAL: bare "new instructions"
#                              mid-sentence, "the new instructions are ...".
#   system-override   WIDENED  word-order variant "override (the) system
#                              prompt". INTENTIONAL: bare "override the
#                              system" (benign in systems prose).
#   system-prefix     WIDENED  pre-colon tolerance only ([ \t]*). Leading-
#                              whitespace tolerance REJECTED: ^\s* under
#                              MULTILINE is O(n^2) on newline floods (measured
#                              19s at 80 KB) and FPs on indented YAML system:
#                              keys. INTENTIONAL: indented SYSTEM:, lone-\r
#                              line endings (MULTILINE ^ anchors after \n
#                              only), other speaker tags (ASSISTANT:, USER:).
#   inst-delimiter    WIDENED  symmetric [/?INST] / </?INST> pairs + Llama-2
#                              <<SYS>>/<</SYS>> (same template-delimiter rule).
#   structural (3)    SWEPT-CLEAN  mechanically defined thresholds/classes.
#   encoding (4)      SWEPT-CLEAN  normalize()-driven + base64 regex (PET-1
#                              heritage thresholds untouched).

_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "ignore-previous",
        # Determiner stack so "ignore all of your previous instructions"
        # doesn't fall between rules (PET-91 fixed the single-determiner
        # case; PET-93 widened to stacks and adjective synonyms).
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
        # "the new instructions are ..." retreated to "your ..." only: the
        # benign corpus flagged "The new instructions are in the README" as a
        # new FP (PET-93 D6 guard), exactly the spec's pre-committed fallback.
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


# Cheap necessary-condition gate for the injection battery (PET-97 latency).
# Every _INJECTION_PATTERNS match contains one of these literal substrings:
#   inst   — "instructions" (ignore-*, disregard A/B, new-instructions),
#            "[INST]"/"<INST>" (inst-delimiter)
#   sys    — "system" (system-override, system-prefix), "<<SYS>>" (inst-delimiter)
#   disregard — "disregard your" (disregard branch C, the lone no-"inst" branch)
#   now    — "you are/'re now" (you-are-now)
# so a candidate matching none cannot match any pattern and skips the 8-pattern
# scan. This collapses the digit-dense worst case (8 patterns x up to 6
# candidates) to one membership pass per candidate, holding the <5ms syntactic
# budget. MUST remain a superset of the pattern anchors if a rule is added or
# widened — test_injection_anchor_is_sound pins it and the full detection suite
# guards it (any dropped anchor reds an existing positive).
_INJECTION_ANCHOR = re.compile(r"inst|sys|disregard|now", re.IGNORECASE)


def _check_injection(
    self: MinimalScanner, normalized: NormalizedText, findings: list[ScanFinding]
) -> bool:
    # Four kinds: plain, leet (PET-97), separator (PET-198), composed
    # (PET-201). Leet is 1:1 length-preserving, so a match span on a leet
    # view is a valid span in `normalized`. Separator and composed views
    # are not 1:1: a hit on those kinds omits position and matched_text
    # and does not write a leet-decoded suffix. Named families consume
    # extra views in their own helpers.
    #
    # Gate each candidate by the cheap anchor first: a candidate matching no
    # injection-pattern anchor cannot match any pattern, so it skips the
    # 8-pattern battery entirely (PET-97 latency — see _INJECTION_ANCHOR).
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
