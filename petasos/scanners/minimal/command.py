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

# --- Obfuscated / destructive command patterns (5 rules, PET-94) ---
#
# Outbound-only (Decision 2): the threat is the agent *emitting/executing*
# commands as tool params (direction="outbound" via ToolCallGuard._scan_params),
# not a human *mentioning* them inbound (curl|sh is the documented installer for
# half the ecosystem). Suppressible (Decision 1 — NOT in _UNSUPPRESSIBLE_RULE_IDS)
# and suppressed by default in code_generation for pipe-to-shell only
# (PET-221). The other four command rules stay active under that profile.
#
# Family invariants (load-bearing — pinned by tests):
#   * severity is HIGH, never CRITICAL (Decision 3) — caps both Tier-3 paths.
#   * frequency weight 3.0 (frequency.py), single-scan ceiling <=5 rules x 3.0 =
#     15 points (== default tier1_threshold; below the 50.0 tier3 floor). This
#     rests on one-finding-per-rule-per-scan (_check_command uses search-then-
#     next-rule, no finditer): N non-overlapping same-rule matches would each
#     survive merge dedup and each count.
#   * patterns run on canonical normalized text plus separator views
#     (PET-211; composed views stay on the injection battery), so homoglyph /
#     invisible-char obfuscation is already unwound by PET-43/44/90.
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


def _check_command(
    self: MinimalScanner, normalized: NormalizedText, findings: list[ScanFinding]
) -> None:
    # Per-view pre-gate (Decision 6 / PET-201): a candidate matching no
    # command anchor cannot match any pattern, so skip the 5-pattern
    # fan-out on that view — the no-match fast path that holds the <5ms
    # outbound budget. Slug-outer, view-inner, first-hit per rule_id.
    views = _family_search_views(normalized)
    if not any(_COMMAND_ANCHOR.search(v) for v in views):
        return
    for slug, pattern, confidence in _COMMAND_PATTERNS:
        rule_id = f"petasos.syntactic.command.{slug}"
        if rule_id in self._suppress_rules:
            continue
        # search-then-next-rule (NO finditer): at most one finding per rule
        # per scan. This is a hard invariant — Decision 3.2's <=15 frequency
        # ceiling depends on it (N non-overlapping same-rule matches would
        # each survive merge dedup and each count).
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
