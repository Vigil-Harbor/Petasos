from __future__ import annotations

import base64
import binascii
import logging
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

_logger = logging.getLogger(__name__)


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

# --- Obfuscated / destructive command patterns (5 rules, PET-94) ---
#
# Outbound-only (Decision 2): the threat is the agent *emitting/executing*
# commands as tool params (direction="outbound" via ToolCallGuard._scan_params),
# not a human *mentioning* them inbound (curl|sh is the documented installer for
# half the ecosystem). Suppressible (Decision 1 — NOT in _UNSUPPRESSIBLE_RULE_IDS)
# and suppressed by default in code_generation (Decision 4).
#
# Family invariants (load-bearing — pinned by tests):
#   * severity is HIGH, never CRITICAL (Decision 3) — caps both Tier-3 paths.
#   * frequency weight 3.0 (frequency.py), single-scan ceiling <=5 rules x 3.0 =
#     15 points (== default tier1_threshold; below the 50.0 tier3 floor). This
#     rests on one-finding-per-rule-per-scan (_check_command uses search-then-
#     next-rule, no finditer): N non-overlapping same-rule matches would each
#     survive merge dedup and each count.
#   * patterns run on NORMALIZED text (same input as _check_injection), so
#     homoglyph/invisible-char obfuscation is already unwound by PET-43/44/90.
#   * case-sensitive (shell command names are; IGNORECASE buys FPs, not recall).
#
# Confidence tiers make every overlapping-span merge deterministic (PIPE-04
# keeps the higher severity-rank, then higher confidence): destructive-recursive
# (0.95) > alias-escape / decode-exec / fetch-exec (0.9) > pipe-to-shell (0.7).
# So \rm -rf /tmp (alias-escape span overlaps destructive-recursive) resolves to
# destructive-recursive; alias/decode/fetch have disjoint leading anchors and
# cannot overlap each other. pipe-to-shell's 0.7 must stay >= the highest
# built-in confidence_floor (research.json = 0.7; Stage 5b filter is `>=`) or it
# silently dies in that profile.
#
# Two trailing-lookahead micro-edges (Design §1):
#   1. Param-text truncation (_MAX_PARAM_TEXT_LEN, guard.py) is bidirectional:
#      it can delete the `|` a negative lookahead needs (benign cell -> finding,
#      fail-noisy/accepted) OR cut the `| sh` tail off a genuine fetch-exec
#      (fail-quiet, out of detection scope by construction; the guard's
#      truncation warning is the operator tripwire).
#   2. `\s*` after `\|` crosses newlines (real POSIX continuations: curl x |\nsh
#      stay caught — the benign cross-line table shape rides along as an accepted
#      FP). The strong rules' body is `[^|\n]*`, which CANNOT cross a newline;
#      that exclusion bounds the accepted-FP blast radius. Widening it to `[^|]*`
#      (to catch multi-line multi-stage pipelines) would re-admit the cross-line
#      benign-table FP — re-decide consciously (the multi-stage miss is pinned).
_COMMAND_PATTERNS: list[tuple[str, re.Pattern[str], float]] = [
    (
        # Generic pipe-to-shell. `(?:ba|z|da)?sh` covers sh/bash/zsh/dash; the
        # optional sudo prefix catches `| sudo bash` (most common privileged
        # installer form) while `| sudo apt install` stays silent (apt is no
        # shell word). `\b` after the shell word rejects `| shellcheck`/`| shasum`;
        # the `(?!\s*[\|)])` tail rejects single-word table cells (`| bash | …`)
        # and paren-closed regex alternations (`(bash|sh)`). Quote-terminal
        # adjacency (`| sh"`) stays HOT deliberately — JSON-serialized nested
        # tool params end commands with quotes — at the cost of an accepted FP
        # on quote-terminal regex strings (`"bash|sh|zsh"`).
        "pipe-to-shell",
        re.compile(r"\|\s*(?:sudo\s+(?:-\S+\s+)*)?(?:ba|z|da)?sh\b(?!\s*[\|)])"),
        0.7,
    ),
    (
        # decode-and-execute. Leading `\b` prevents `mybase64 …`; bounded
        # `[^|\n]*` keeps the match in one pipeline segment. Trailing pipe-only
        # lookahead `(?!\s*\|)` kills table cells while keeping parens hot
        # ($(echo x | base64 -d | sh) still fires).
        "decode-exec",
        re.compile(
            r"\b(?:base64\s+(?:-d|-D|--decode)|xxd\s+-r(?:\s+-p)?|openssl\s+enc\s+-d)"
            r"[^|\n]*\|\s*(?:sudo\s+(?:-\S+\s+)*)?(?:ba|z|da)?sh\b(?!\s*\|)"
        ),
        0.9,
    ),
    (
        # fetch-and-execute. `curl … | sudo sh` (canonical privileged installer)
        # and subshell wrappers `(curl x | sh)` / `$(curl x | sh)` fire (parens
        # deliberately not in this rule's lookahead). Trailing pipe-only
        # lookahead kills tools-table rows `| wget | bash | …`.
        "fetch-exec",
        re.compile(
            r"\b(?:curl|wget)\b[^|\n]*\|\s*(?:sudo\s+(?:-\S+\s+)*)?(?:ba|z|da)?sh\b(?!\s*\|)"
        ),
        0.9,
    ),
    (
        # backslash alias-escape. The backslash itself is the signal (it defeats
        # shell aliases and literal-string approval gates), so ANY escaped
        # invocation of a privileged verb is a TP regardless of argument
        # destructiveness; the argument-shape class only rejects prose/LaTeX
        # (`{\rm Roman}` letter, `{\rm 0.95}` decimal run, `{\rm -1}` -digit)
        # and Windows path prose (`C:\rmdir\backup` — no whitespace after verb).
        "alias-escape",
        re.compile(r"\\(?:rm|mv|dd|chmod|chown|mkfs|shred)\s+(?:-[a-zA-Z]|/|~|[0-7]{3,4}\b)"),
        0.9,
    ),
    (
        # destructive-recursive: rm -rf onto an absolute/homedir target, dd onto
        # a real device, or mkfs.* invocation. Dangerous-target boundary is
        # deliberate — any absolute (`/…`) or homedir (`~…`, `$HOME`) target is a
        # TP by design (distinguishing safe/unsafe absolute paths is unwinnable
        # pattern-side; code_generation suppresses the family). Relative targets
        # stay silent (`rm -rf build/`); `$HOMEBREW_CACHE` stays silent (the `\b`
        # after HOME); benign dd sinks (/dev/null|stdout|stderr|zero|shm/) and
        # bare `mkfs` prose stay silent.
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

# --- Agent-directed fetch/install directive (PET-154) ---
#
# Compositional injection-class detector (Decisions D1/D2/DS1-DS3): a finding
# requires an agent-address MARKER (factor 1) co-occurring with a fetch/install/
# execute ACTION (factor 2) and an external-RESOURCE cue (factor 3), all within a
# single physical line. The marker is the precision lever — a README describes an
# install; it does not address the agent. Direction-blind, unsuppressible, HIGH
# (never CRITICAL). Patterns run on NORMALIZED text (same input as
# _check_injection), so homoglyph/invisible-char obfuscation is already unwound,
# and via the PET-98 rescan path for decoded carriers. Final patterns refined
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

# WEAK speaker-tag marker (Decision DS4) — `Assistant:` prefixes vast amounts of
# benign transcript, so it pairs ONLY with the high-danger archive/exec resource
# class (not a bare document URL). No re.MULTILINE: the per-line helper applies it
# to one physical line, where `^` already anchors the line start.
_AGENT_DIRECTIVE_SPEAKER_TAG: list[re.Pattern[str]] = [
    re.compile(r"^\s*assistant\s*:", re.IGNORECASE),
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

_AGENT_DIRECTIVE_RULE_IDS: frozenset[str] = frozenset(
    {"petasos.syntactic.injection.agent-directed-fetch"}
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


# --- Structural checks ---

_BINARY_PATTERN = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")

# --- Encoding detection ---

_BASE64_PATTERN = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")

# --- Decode-and-rescan (PET-98) ---
#
# Separate detector battery with lower floors than _BASE64_PATTERN's 40-char
# LOW-flag threshold (Decision 6): decode + injection-match is self-validating, so
# a short blob that does not decode to an injection phrase emits nothing and adds
# no false positive. Span discovery runs off the base64 detector only — the hex
# alphabet [0-9a-fA-F] is a strict subset of the base64 alphabet at the same
# 16-char floor, so every hex run is contained in a base64 span and each physical
# span costs exactly one budget slot while being attempted under both codecs
# (Decision 4 / § Design step 2).
_BASE64_BLOB_DETECTOR = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")
_HEX_BLOB_DETECTOR = re.compile(r"(?:[0-9a-fA-F]{2}){8,}")
_ROT13_TABLE = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    "NOPQRSTUVWXYZABCDEFGHIJKLMnopqrstuvwxyzabcdefghijklm",
)
_DECODE_MAX_BLOBS = 16  # per-input detected-span attempt cap (base64+hex)
_DECODE_MAX_BYTES = 8192  # per-blob decoded-size cap (scan first N bytes)
_DECODE_SNIPPET_CAP = 80  # message snippet cap (matches leet [:80])


@dataclass(frozen=True)
class _DecodeCandidate:
    """A decoded plaintext to rescan through the injection/role-switch batteries.

    ``scan_text`` is what the patterns search. For a base64/hex blob,
    ``position``/``matched_text`` are the fixed raw-space blob span (consistent
    with base64-in-text / binary-content raw-space positions). For the ROT13
    view they are ``None`` and resolved per-match against ``origin_text`` (=
    ``normalized.normalized``) in normalized-space coordinates — consistent with
    the _check_injection leet path, which reports the original attack bytes in
    matched_text and names the decoded form in the message.
    """

    carrier: str
    scan_text: str
    position: Position | None
    matched_text: str | None
    origin_text: str


def _try_b64decode(span: str) -> bytes | None:
    try:
        return base64.b64decode(span, validate=True)
    except (binascii.Error, ValueError):
        return None


def _try_hexdecode(span: str) -> bytes | None:
    try:
        return bytes.fromhex(span)
    except ValueError:
        return None


def _decode_bytes(raw: bytes) -> str | None:
    """Bytes → text under Decision 5's size-cap-aware rule.

    Under the per-blob cap: strict UTF-8 — the FP discipline that keeps binary
    assets (image/font data, random tokens, gzip) quiet. Over the cap: decode the
    first cap bytes with ``errors="ignore"`` so a code point split by the hard
    byte truncation drops only its trailing partial sequence, never an in-prefix
    injection. The ``errors=`` divergence is deliberate and applies only to the
    truncated tail.
    """
    if len(raw) <= _DECODE_MAX_BYTES:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return raw[:_DECODE_MAX_BYTES].decode("utf-8", errors="ignore")


def _resolve_finding_shape(cand: _DecodeCandidate, m: re.Match[str]) -> tuple[Position, str]:
    """Resolve (position, matched_text) for a match on a decoded candidate.

    Blob candidates carry a fixed raw-space span; the ROT13 view resolves per
    match against its origin text in normalized-space coordinates.
    """
    if cand.position is not None:
        assert cand.matched_text is not None
        return cand.position, cand.matched_text
    return Position(start=m.start(), end=m.end()), cand.origin_text[m.start() : m.end()]


# Cheap necessary-condition gate for the injection battery (PET-97 latency).
# Every _INJECTION_PATTERNS match contains one of these literal substrings:
#   inst   — "instructions" (ignore-*, disregard A/B, new-instructions),
#            "[INST]"/"<INST>" (inst-delimiter)
#   sys    — "system" (system-override, system-prefix), "<<SYS>>" (inst-delimiter)
#   disregard — "disregard your" (disregard branch C, the lone no-"inst" branch)
#   now    — "you are/'re now" (you-are-now)
# so a candidate matching none cannot match any pattern and skips the 8-pattern
# scan. This collapses the digit-dense worst case (8 patterns x up to 3 leet
# candidates) to one membership pass per candidate, holding the <5ms syntactic
# budget. MUST remain a superset of the pattern anchors if a rule is added or
# widened — test_injection_anchor_is_sound pins it and the full detection suite
# guards it (any dropped anchor reds an existing positive).
_INJECTION_ANCHOR = re.compile(r"inst|sys|disregard|now", re.IGNORECASE)

# Cheap necessary-condition gate for the command battery (PET-94 / Decision 6,
# mirroring _INJECTION_ANCHOR). The alternation is the literal-substring superset
# of every _COMMAND_PATTERNS mandatory literal: `sh` covers sh/bash/zsh/dash by
# substring; `\\` covers the alias-escape leading backslash; the rest are the
# command verbs. Compiled IGNORECASE for membership only — the anchor is a
# NECESSARY, not sufficient, condition, so over-matching here costs at most one
# pattern pass and can never cause a missed detection (the patterns stay
# case-sensitive). MUST remain a superset of the pattern literals if a rule is
# added or widened (e.g. `| ksh`) — TestCommandAnchorSoundness pins per-branch
# reachability and test_command_anchor_equivalence proves the gate is pure
# pruning.
_COMMAND_ANCHOR = re.compile(
    r"sh|base64|xxd|openssl|curl|wget|rm|dd|mkfs|chmod|chown|shred|mv|\\",
    re.IGNORECASE,
)

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

_COMMAND_RULE_IDS: frozenset[str] = frozenset(
    f"petasos.syntactic.command.{slug}" for slug, _pattern, _confidence in _COMMAND_PATTERNS
)

RULE_TAXONOMY: frozenset[str] = (
    _INJECTION_RULE_IDS
    | _ROLE_SWITCH_RULE_IDS
    | _STRUCTURAL_RULE_IDS
    | _ENCODING_RULE_IDS
    | _COMMAND_RULE_IDS
    | _AGENT_DIRECTIVE_RULE_IDS  # PET-154
)

_ALL_INJECTION_IDS = (
    _INJECTION_RULE_IDS | _ROLE_SWITCH_RULE_IDS | _AGENT_DIRECTIVE_RULE_IDS  # PET-154
)

# The command family (_COMMAND_RULE_IDS, PET-94) is deliberately OUTSIDE this set
# — it is suppressible (Decision 1). The unsuppressible set exists to prevent
# profile-driven evasion of *injection detection* (SYN-08/PROF-04); command
# rules detect *content dangerous to execute*, not content that manipulates the
# model, and legitimate workloads (code generation) routinely emit it, so
# code_generation suppresses the family by config. A future family-author who
# wants a non-suppressible command rule must re-decide this consciously.
_UNSUPPRESSIBLE_RULE_IDS = _STRUCTURAL_RULE_IDS | _ALL_INJECTION_IDS


class MinimalScanner:
    def __init__(
        self,
        *,
        max_payload_bytes: int = 524_288,
        max_json_depth: int = 10,
        suppress_rules: frozenset[str] = frozenset(),
        decode_encoded_payloads: bool = True,
    ) -> None:
        self._max_payload_bytes = max_payload_bytes
        self._max_json_depth = max_json_depth
        self._suppress_rules = suppress_rules - _UNSUPPRESSIBLE_RULE_IDS
        self._decode_encoded_payloads = decode_encoded_payloads

    def with_suppress_rules(self, additional: frozenset[str]) -> MinimalScanner:
        return MinimalScanner(
            max_payload_bytes=self._max_payload_bytes,
            max_json_depth=self._max_json_depth,
            suppress_rules=self._suppress_rules | additional,
            decode_encoded_payloads=self._decode_encoded_payloads,
        )

    def set_decode_encoded_payloads(self, flag: bool) -> None:
        """PET-126: flip the decode toggle in place (read live at scan time).

        The one targeted in-place mutation in the reconfigure path: MinimalScanner
        carries no session state, so a caller-supplied scanner keeps its other
        tunables (``max_payload_bytes``, ``max_json_depth``, ``suppress_rules``)
        and its object identity rather than being rebuilt (spec Decision 1).
        """
        self._decode_encoded_payloads = flag

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
            findings = self._scan_impl(text, direction)
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

    def _scan_impl(self, text: str, direction: Direction) -> list[ScanFinding]:
        findings: list[ScanFinding] = []

        # Step 1: Structural checks on raw input
        self._check_structural(text, findings)

        # Step 2: Normalize
        normalized = normalize(text)

        # Step 3: Injection patterns on normalized text + leet views (PET-97)
        injection_matched = self._check_injection(normalized, findings)

        # Step 4: Role-switch detection on normalized text
        self._check_role_switch(normalized.normalized, findings)

        # Step 4c: Agent-directed fetch/install directive (PET-154) — injection
        # class, direction-blind (Decision D2), exactly like Steps 3-4. The
        # boolean feeds the Step-7 escalation co-occurrence flag (Decision DS2).
        agent_directive_matched = self._check_agent_directive(normalized.normalized, findings)

        # Step 4b: Destructive/obfuscated command family (PET-94) — outbound
        # only (Decision 2). The `direction` parameter goes from accepted-but-
        # ignored to used; the public scan() signature is unchanged.
        if direction == "outbound":
            self._check_command(normalized.normalized, findings)
        elif direction not in ("inbound", "outbound"):
            # Silent-off is the worst failure mode for a security family: an
            # off-Literal direction from an untyped host (e.g. "OUTBOUND",
            # " outbound") would skip the family indistinguishably from clean
            # content. Emit a grep-able debug tripwire instead of hard-validating
            # — no other scanner validates direction, and raising would break
            # source-compatibility (Design §2).
            _logger.debug("command family skipped: unrecognized direction %r", direction)

        # Step 5: Decode-and-rescan reversible encodings (PET-98). Runs as its own
        # step (not inside the base64-in-text suppression guard), so the decoded
        # injection fires even when the LOW base64-in-text flag is suppressed.
        decoded_matched = self._check_encoded_payloads(text, normalized, findings)

        # Step 6: Encoding detection (LOW base64-in-text flag, etc.)
        self._check_encoding(text, normalized, findings)

        # Step 7: Invisible-chars escalation. OR the decode result and the
        # agent-directive result into the co-occurrence flag so a decode-only
        # injection or an agent-directive (plain or decoded) still escalates an
        # invisible-chars finding (consistency with the plain path; Decision DS2).
        self._apply_escalation(
            findings, injection_matched or decoded_matched or agent_directive_matched
        )

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
        # Plain text plus the leet-decoded views (PET-97). The fold is 1:1
        # length-preserving, so a match span on a view is a valid span in
        # `normalized` — matched_text shows the original (leet) attack bytes
        # while the decoded form is named in the message. Role-switch triggers
        # deliberately never see the views (PET-97 Decision 2: decode FPs).
        #
        # Gate each candidate by the cheap anchor first: a candidate matching no
        # injection-pattern anchor cannot match any pattern, so it skips the
        # 8-pattern battery entirely (PET-97 latency — see _INJECTION_ANCHOR).
        candidates = [
            (text, is_view)
            for text, is_view in (
                (normalized.normalized, False),
                *((v, True) for v in normalized.leet_views),
            )
            if _INJECTION_ANCHOR.search(text)
        ]
        if not candidates:
            return False
        any_matched = False
        for slug, pattern in _INJECTION_PATTERNS:
            rule_id = f"petasos.syntactic.injection.{slug}"
            if rule_id in self._suppress_rules:
                continue
            for text, is_view in candidates:
                m = pattern.search(text)
                if m is None:
                    continue
                any_matched = True
                # Truncated: \s+ runs make m.group() attacker-inflatable
                # (cf. the base64-in-text [:50] cap).
                decoded = f" (leet-decoded: {m.group()[:80]!r})" if is_view else ""
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

    def _check_command(self, normalized_text: str, findings: list[ScanFinding]) -> None:
        # Pre-gate first (Decision 6): a candidate matching no command anchor
        # cannot match any pattern, so skip the 5-pattern fan-out — the no-match
        # fast path that holds the <5ms outbound budget. The exact
        # _check_injection shape.
        if not _COMMAND_ANCHOR.search(normalized_text):
            return
        for slug, pattern, confidence in _COMMAND_PATTERNS:
            rule_id = f"petasos.syntactic.command.{slug}"
            if rule_id in self._suppress_rules:
                continue
            # search-then-next-rule (NO finditer): at most one finding per rule
            # per scan. This is a hard invariant — Decision 3.2's <=15 frequency
            # ceiling depends on it (N non-overlapping same-rule matches would
            # each survive merge dedup and each count).
            m = pattern.search(normalized_text)
            if m is None:
                continue
            findings.append(
                ScanFinding(
                    rule_id=rule_id,
                    finding_type="command",
                    severity=Severity.HIGH,
                    confidence=confidence,
                    message=f"Obfuscated/destructive command pattern matched: {slug}",
                    scanner_name=self.name,
                    position=Position(start=m.start(), end=m.end()),
                    # Cap: bounded `[^|\n]*` runs make m.group() attacker-
                    # inflatable (cf. the base64-in-text [:50] cap).
                    matched_text=normalized_text[m.start() : m.end()][:120],
                )
            )

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

    def _check_agent_directive(self, normalized_text: str, findings: list[ScanFinding]) -> bool:
        # PET-154: agent-address marker × fetch/install/execute action × external
        # resource, per physical line (the _agent_directive_line_hit conjunction).
        # The suppress check is omitted because the rule_id is stripped from
        # _suppress_rules at construction (Decision D1) — same idiom as the rescan
        # injection battery. At most one finding per scan (Decision DS3).
        hit = _agent_directive_line_hit(normalized_text)
        if hit is None:
            return False
        start, end = hit
        findings.append(
            ScanFinding(
                rule_id="petasos.syntactic.injection.agent-directed-fetch",
                finding_type="injection",
                severity=Severity.HIGH,
                confidence=1.0,
                message="Agent-directed fetch/install directive detected",
                scanner_name=self.name,
                position=Position(start=start, end=end),
                # Cap: marker patterns contain \s+ runs -> attacker-inflatable
                # group (cf. the base64-in-text [:50] cap).
                matched_text=normalized_text[start:end][:120],
            )
        )
        return True

    def _check_encoded_payloads(
        self,
        raw_text: str,
        normalized: NormalizedText,
        findings: list[ScanFinding],
    ) -> bool:
        """Decode reversible-encoding blobs and rescan the plaintext (PET-98).

        Locates base64/hex blob spans in the raw text and computes one ROT13 view
        of the normalized text, decodes each under strict DoS bounds (Decision 4),
        then runs the injection battery (anchor-gated) and the role-switch battery
        (unconditional, Decision 2 / § step 5) over every decoded candidate. A
        match emits the underlying injection / role-switch finding at its native
        severity, reusing the existing rule_id — no new rule_id is minted. Runs
        independently of base64-in-text suppression (Decision 3). Returns whether
        any candidate matched (feeds the escalation co-occurrence flag).
        """
        if not self._decode_encoded_payloads:
            return False

        candidates: list[_DecodeCandidate] = []

        # base64-detector spans are the physical spans (§ Design step 2): the hex
        # alphabet is a strict subset of the base64 alphabet at the same 16-char
        # floor, so every hex run is contained in a base64 span. One budget slot
        # per physical span; both codecs are attempted per span (<=2 decodes), so
        # a delimited hex blob — which the base64 detector also matches — still
        # decodes. The cap counts attempted spans, not successful decodes, so a
        # malformed-blob flood stays bounded.
        attempts = 0
        for m in _BASE64_BLOB_DETECTOR.finditer(raw_text):
            if attempts >= _DECODE_MAX_BLOBS:
                break
            attempts += 1
            span = m.group()
            blob_position = Position(start=m.start(), end=m.end())
            blob_matched = span[:_DECODE_SNIPPET_CAP]
            for carrier, raw in (("base64", _try_b64decode(span)), ("hex", _try_hexdecode(span))):
                if raw is None:
                    continue
                decoded = _decode_bytes(raw)
                if decoded is None:
                    continue
                candidates.append(
                    _DecodeCandidate(carrier, decoded, blob_position, blob_matched, "")
                )

        # ROT13: a single always-on, length-preserving view, bounded to the
        # per-blob byte cap (Decision 4) so the translate + scan stays O(cap).
        # ROT13 has no structural signature, so it is decoded unconditionally as
        # one extra view rather than detected (Decision 7). Offsets map 1:1 onto
        # normalized.normalized, so a match span there is valid in normalized space.
        rot13_view = normalized.normalized[:_DECODE_MAX_BYTES].translate(_ROT13_TABLE)
        candidates.append(_DecodeCandidate("rot13", rot13_view, None, None, normalized.normalized))

        matched = False
        for cand in candidates:
            if self._rescan_candidate(cand, findings):
                matched = True
        return matched

    def _rescan_candidate(self, cand: _DecodeCandidate, findings: list[ScanFinding]) -> bool:
        matched = False

        # Injection battery — anchor-gated exactly as _check_injection gates leet
        # views: a candidate carrying no injection anchor skips the 8-pattern
        # battery. The suppress check is omitted because injection rule_ids are
        # stripped from _suppress_rules at construction (Decision 3).
        if _INJECTION_ANCHOR.search(cand.scan_text):
            for slug, pattern in _INJECTION_PATTERNS:
                m = pattern.search(cand.scan_text)
                if m is None:
                    continue
                position, matched_text = _resolve_finding_shape(cand, m)
                snippet = m.group()[:_DECODE_SNIPPET_CAP]
                findings.append(
                    ScanFinding(
                        rule_id=f"petasos.syntactic.injection.{slug}",
                        finding_type="injection",
                        severity=Severity.HIGH,
                        confidence=1.0,
                        message=(
                            f"Injection pattern matched: {slug} "
                            f"({cand.carrier}-decoded: {snippet!r})"
                        ),
                        scanner_name=self.name,
                        position=position,
                        matched_text=matched_text,
                    )
                )
                matched = True

        # Role-switch battery — NOT anchor-gated (the injection anchor is not a
        # superset of the role-switch triggers, so gating here would drop a decoded
        # "act as DAN with no restrictions"). At most one finding per candidate,
        # mirroring the live single-emit _check_role_switch.
        if self._rescan_role_switch(cand, findings):
            matched = True

        # Agent-directive battery (PET-154 / Decision D6) — runs its OWN
        # _AGENT_DIRECTIVE_ANCHOR gate (inside the shared helper), not the
        # injection anchor (which is not a superset of the agent markers),
        # mirroring how _rescan_role_switch runs unconditionally here.
        if self._rescan_agent_directive(cand, findings):
            matched = True

        return matched

    def _rescan_role_switch(self, cand: _DecodeCandidate, findings: list[ScanFinding]) -> bool:
        trigger_match = None
        for pat in _ROLE_TRIGGERS:
            trigger_match = pat.search(cand.scan_text)
            if trigger_match:
                break
        if trigger_match is None:
            return False

        grant_match = None
        for pat in _ROLE_GRANTS:
            grant_match = pat.search(cand.scan_text)
            if grant_match:
                break

        position, matched_text = _resolve_finding_shape(cand, trigger_match)
        if grant_match is not None:
            rule_id = "petasos.syntactic.injection.role-switch-capability"
            severity = Severity.HIGH
            message = f"Role-switch with capability grant detected ({cand.carrier}-decoded)"
        else:
            rule_id = "petasos.syntactic.injection.role-switch-only"
            severity = Severity.LOW
            message = (
                f"Role-switch trigger detected without capability grant ({cand.carrier}-decoded)"
            )
        findings.append(
            ScanFinding(
                rule_id=rule_id,
                finding_type="injection",
                severity=severity,
                confidence=1.0,
                message=message,
                scanner_name=self.name,
                position=position,
                matched_text=matched_text,
            )
        )
        return True

    def _rescan_agent_directive(self, cand: _DecodeCandidate, findings: list[ScanFinding]) -> bool:
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
        # catches. Normalize the blob branch before the conjunction; its finding
        # reports the fixed carrier span (cand.position/.matched_text), so detecting
        # on a normalized view does not disturb offset mapping. The ROT13 branch
        # must stay raw — its hit offsets index 1:1 into origin_text and NFKC would
        # desync them (origin_text is itself normalized-space).
        scan_text = (
            normalize(cand.scan_text).normalized if cand.position is not None else cand.scan_text
        )
        hit = _agent_directive_line_hit(scan_text)
        if hit is None:
            return False
        start, end = hit
        if cand.position is not None:  # blob candidate: fixed raw-space blob span
            assert cand.matched_text is not None
            position, matched_text = cand.position, cand.matched_text
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
