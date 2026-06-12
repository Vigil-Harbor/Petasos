from __future__ import annotations

import re
import time
from dataclasses import dataclass

from petasos._types import (
    Direction,
    NormalizedText,
    Position,
    ScanFinding,
    ScanResult,
    Severity,
)
from petasos.normalize import normalize


@dataclass(frozen=True)
class SyntacticRule:
    rule_id: str
    category: str
    severity: Severity
    can_suppress: bool
    description: str


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

# --- Role-switch detection ---

_ROLE_TRIGGERS: list[re.Pattern[str]] = [
    re.compile(r"you\s+are\s+a", re.IGNORECASE),
    re.compile(r"act\s+as", re.IGNORECASE),
    re.compile(r"pretend\s+you\s+are", re.IGNORECASE),
    re.compile(r"roleplay\s+as", re.IGNORECASE),
    # PET-93 additions: contraction and from-now-on forms. The [,;]? admits
    # the canonical comma form ("From now on, you will be DAN"); other
    # punctuation separators are documented INTENTIONAL.
    re.compile(r"pretend\s+to\s+be", re.IGNORECASE),
    re.compile(r"you['’ʼ]re\s+an?\b", re.IGNORECASE),
    re.compile(r"from\s+now\s+on[,;]?\s+you(?:['’ʼ]re|\s+(?:are|will\s+be))", re.IGNORECASE),
]

_ROLE_GRANTS: list[re.Pattern[str]] = [
    re.compile(r"no\s+restrictions", re.IGNORECASE),
    re.compile(r"no\s+limits", re.IGNORECASE),
    re.compile(r"without\s+filters", re.IGNORECASE),
    re.compile(r"DAN\s+mode", re.IGNORECASE),
    re.compile(r"developer\s+mode", re.IGNORECASE),
    # PET-93 additions (mirrored in benign_corpus.SANCTIONED_NEW_GRANTS for
    # the MIGRATED attribution check).
    re.compile(r"without\s+(?:restrictions|limits)", re.IGNORECASE),
    re.compile(r"no\s+filters", re.IGNORECASE),
    re.compile(r"jailbreak\s+mode", re.IGNORECASE),
]

# --- Structural checks ---

_BINARY_PATTERN = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")

# --- Encoding detection ---

_BASE64_PATTERN = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")

# --- Rule taxonomy ---

_INJECTION_RULE_IDS = frozenset(
    f"petasos.syntactic.injection.{slug}" for slug, _ in _INJECTION_PATTERNS
)

_ROLE_SWITCH_RULE_IDS = frozenset(
    [
        "petasos.syntactic.injection.role-switch-capability",
        "petasos.syntactic.injection.role-switch-only",
    ]
)

_STRUCTURAL_RULE_IDS = frozenset(
    [
        "petasos.syntactic.structural.oversized-payload",
        "petasos.syntactic.structural.excessive-depth",
        "petasos.syntactic.structural.binary-content",
    ]
)

_ENCODING_RULE_IDS = frozenset(
    [
        "petasos.syntactic.encoding.invisible-chars",
        "petasos.syntactic.encoding.base64-in-text",
        "petasos.syntactic.encoding.homoglyph-substitution",
        "petasos.syntactic.encoding.rtl-override",
    ]
)

RULE_TAXONOMY: frozenset[str] = (
    _INJECTION_RULE_IDS | _ROLE_SWITCH_RULE_IDS | _STRUCTURAL_RULE_IDS | _ENCODING_RULE_IDS
)

_ALL_INJECTION_IDS = _INJECTION_RULE_IDS | _ROLE_SWITCH_RULE_IDS

_UNSUPPRESSIBLE_RULE_IDS = _STRUCTURAL_RULE_IDS | _ALL_INJECTION_IDS


class MinimalScanner:
    def __init__(
        self,
        *,
        max_payload_bytes: int = 524_288,
        max_json_depth: int = 10,
        suppress_rules: frozenset[str] = frozenset(),
    ) -> None:
        self._max_payload_bytes = max_payload_bytes
        self._max_json_depth = max_json_depth
        self._suppress_rules = suppress_rules - _UNSUPPRESSIBLE_RULE_IDS

    def with_suppress_rules(self, additional: frozenset[str]) -> MinimalScanner:
        return MinimalScanner(
            max_payload_bytes=self._max_payload_bytes,
            max_json_depth=self._max_json_depth,
            suppress_rules=self._suppress_rules | additional,
        )

    @property
    def name(self) -> str:
        return "minimal"

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        start_time = time.perf_counter()
        try:
            findings = self._scan_impl(text)
            elapsed = (time.perf_counter() - start_time) * 1000
            return ScanResult(
                scanner_name=self.name,
                findings=tuple(findings),
                duration_ms=elapsed,
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - start_time) * 1000
            return ScanResult(
                scanner_name=self.name,
                findings=(),
                duration_ms=elapsed,
                error=str(exc),
            )

    def _scan_impl(self, text: str) -> list[ScanFinding]:
        findings: list[ScanFinding] = []

        # Step 1: Structural checks on raw input
        self._check_structural(text, findings)

        # Step 2: Normalize
        normalized = normalize(text)

        # Step 3: Injection patterns on normalized text + leet views (PET-97)
        injection_matched = self._check_injection(normalized, findings)

        # Step 4: Role-switch detection on normalized text
        self._check_role_switch(normalized.normalized, findings)

        # Step 5: Encoding detection
        self._check_encoding(text, normalized, findings)

        # Step 6: Invisible-chars escalation
        self._apply_escalation(findings, injection_matched)

        return findings

    def _check_structural(self, text: str, findings: list[ScanFinding]) -> None:
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
                        f"Payload size {payload_size} bytes exceeds limit "
                        f"{self._max_payload_bytes}"
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

    def _check_json_depth(self, text: str) -> int:
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
            elif ch in ("}", "]"):
                if depth > 0:
                    depth -= 1
        if not has_brackets:
            return 0
        return max_depth

    def _check_injection(self, normalized: NormalizedText, findings: list[ScanFinding]) -> bool:
        # Plain text first, then the leet-decoded views (PET-97). The fold is
        # 1:1 length-preserving, so a match span on a view is a valid span in
        # `normalized` — matched_text shows the original (leet) attack bytes
        # while the decoded form is named in the message. Role-switch triggers
        # deliberately never see the views (PET-97 Decision 2: decode FPs).
        texts = (normalized.normalized, *normalized.leet_views)
        any_matched = False
        for slug, pattern in _INJECTION_PATTERNS:
            rule_id = f"petasos.syntactic.injection.{slug}"
            if rule_id in self._suppress_rules:
                continue
            for idx, candidate in enumerate(texts):
                m = pattern.search(candidate)
                if m is None:
                    continue
                any_matched = True
                # Truncated: \s+ runs make m.group() attacker-inflatable
                # (cf. the base64-in-text [:50] cap).
                decoded = f" (leet-decoded: {m.group()[:80]!r})" if idx > 0 else ""
                findings.append(
                    ScanFinding(
                        rule_id=rule_id,
                        finding_type="injection",
                        severity=Severity.HIGH,
                        confidence=1.0,
                        message=f"Injection pattern matched: {slug}{decoded}",
                        scanner_name=self.name,
                        position=Position(start=m.start(), end=m.end()),
                        matched_text=normalized.normalized[m.start() : m.end()],
                    )
                )
                break
        return any_matched

    def _check_role_switch(self, normalized_text: str, findings: list[ScanFinding]) -> None:
        cap_rule_id = "petasos.syntactic.injection.role-switch-capability"
        only_rule_id = "petasos.syntactic.injection.role-switch-only"

        trigger_match = None
        for pat in _ROLE_TRIGGERS:
            trigger_match = pat.search(normalized_text)
            if trigger_match:
                break

        if trigger_match is None:
            return

        grant_match = None
        for pat in _ROLE_GRANTS:
            grant_match = pat.search(normalized_text)
            if grant_match:
                break

        if grant_match is not None:
            if cap_rule_id not in self._suppress_rules:
                findings.append(
                    ScanFinding(
                        rule_id=cap_rule_id,
                        finding_type="injection",
                        severity=Severity.HIGH,
                        confidence=1.0,
                        message="Role-switch with capability grant detected",
                        scanner_name=self.name,
                        position=Position(start=trigger_match.start(), end=trigger_match.end()),
                        matched_text=trigger_match.group(),
                    )
                )
        else:
            if only_rule_id not in self._suppress_rules:
                findings.append(
                    ScanFinding(
                        rule_id=only_rule_id,
                        finding_type="injection",
                        severity=Severity.LOW,
                        confidence=1.0,
                        message="Role-switch trigger detected without capability grant",
                        scanner_name=self.name,
                        position=Position(start=trigger_match.start(), end=trigger_match.end()),
                        matched_text=trigger_match.group(),
                    )
                )

    def _check_encoding(
        self,
        raw_text: str,
        normalized: object,
        findings: list[ScanFinding],
    ) -> None:
        from petasos._types import NormalizedText as _NT

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
                    message=(
                        f"{normalized.invisible_chars_stripped} invisible character(s) stripped"
                    ),
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

    def _apply_escalation(self, findings: list[ScanFinding], injection_matched: bool) -> None:
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
