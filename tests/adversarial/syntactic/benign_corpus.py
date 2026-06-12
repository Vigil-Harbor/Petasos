"""Benign/FP corpus for the PET-93 syntactic rule audit (spec D6).

`BENIGN_CORPUS` holds curated benign snippets: ordinary chat/dev lines,
near-trigger prose, config pastes, and non-security repo-doc excerpts.
None of them is an injection attempt; any injection-type finding on one of
them is a false positive.

Three read-only disposition mappings pin the sanctioned FP surface
(snippet -> frozenset of full dotted rule_ids with finding_type "injection"):

- ``PRE_EXISTING``  — fired under the pre-PET-93 HEAD rules (captured by a
  scripted run at HEAD before any widening landed; injection-type findings
  only, the same filter the guard applies).
- ``ACCEPTED_CLASS`` — fire only post-widening, where the fire is a
  verdict-row-sanctioned class extension (PET-93 spec rows 2/4/9-10).
- ``MIGRATED``      — the sole non-monotonic widening: grant-list additions
  flip a HEAD `role-switch-only` pin to `role-switch-capability` (the
  either/or emission in MinimalScanner._check_role_switch). Each entry's
  snippet must match one of the sanctioned new grant patterns
  (``SANCTIONED_NEW_GRANTS``) or it is a regression, not a migration.

The guard test (tests/test_minimal_scanner.py::TestBenignCorpusGuard)
asserts per snippet: firing injection-type rule_ids == union of its pinned
dispositions, and every pinned rule_id is in ``WIDENED_RULE_IDS``.

``WIDENED_RULE_IDS`` equals the full injection-family rule_id set this
cycle (every injection rule carries a WIDEN verdict in PET-93), so the
subset check provides typo/family hygiene and failure-message quality —
not WIDEN-vs-SWEEP discrimination.
"""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

_RID = "petasos.syntactic.injection."

WIDENED_RULE_IDS: frozenset[str] = frozenset(
    {
        f"{_RID}ignore-previous",
        f"{_RID}ignore-all",
        f"{_RID}disregard",
        f"{_RID}you-are-now",
        f"{_RID}new-instructions",
        f"{_RID}system-override",
        f"{_RID}system-prefix",
        f"{_RID}inst-delimiter",
        f"{_RID}role-switch-capability",
        f"{_RID}role-switch-only",
    }
)

# Sanctioned new grant patterns (PET-93 rows 9-10) — the MIGRATED attribution
# anchor: a migration candidate whose snippet matches none of these is a
# regression and must be investigated, not pinned.
SANCTIONED_NEW_GRANTS: tuple[re.Pattern[str], ...] = (
    re.compile(r"without\s+(?:restrictions|limits)", re.IGNORECASE),
    re.compile(r"no\s+filters", re.IGNORECASE),
    re.compile(r"jailbreak\s+mode", re.IGNORECASE),
)

BENIGN_CORPUS: tuple[str, ...] = (
    # --- ordinary chat / dev conversation lines ---
    "Hello, how is the migration going today?",
    "Can you summarize the meeting notes from yesterday?",
    "The deploy finished without errors, finally.",
    "Let me know when the review is done.",
    "Thanks, that explanation really cleared things up.",
    "We should refactor this module next sprint.",
    "The linter flagged two unused imports in the new file.",
    "Could you paste the stack trace from the failing test?",
    "I rebased the branch onto master this morning.",
    "you're a great help",
    "You're an excellent reviewer, thanks for the catch.",
    "you are a great help",
    "act as soon as you can on that ticket",
    "From now on you are responsible for deployments.",
    "you're now ready to deploy",
    "We agreed there are no limits on file size for uploads.",
    "act as a sounding board without limits on scope",
    # --- near-trigger benign prose ---
    "disregard your earlier email, the times changed",
    "the system override switch on the panel is red",
    "Please disregard the instructions on page 4; they are outdated.",
    "forget the instructions, just run the installer",
    "ignore the instructions in step 3 if you already installed it",
    "Just ignore your instructions folder, it's stale.",
    "The new instructions are in the README somewhere.",
    "He chose to override the system entirely and write his own.",
    "Forget the previous draft, I rewrote it.",
    "She decided to ignore previous warnings about the API.",
    "pretend you didn't see that typo",
    "The DAN protocol in networking has nothing to do with chat.",
    "developer experience is a priority this quarter",
    # --- config / structured pastes ---
    "retries: 3\ntimeout: 30\nverbose: false",
    "  system: respond concisely and cite sources",
    "host: localhost\nport: 8080\n  system: gateway-v2",
    "[settings]\nmode = production\nlevel = info",
    "PATH=/usr/local/bin:/usr/bin",
    "user@host:~$ pip list | head",
    # --- non-security repo-doc excerpts (install/build/usage prose) ---
    "pip install petasos",
    "Build backend is Hatch, configured in pyproject.toml.",
    "Run the test suite with pytest from the repository root.",
    "Scanner backends are pip extras, not hard dependencies.",
    "The base install ships with zero required ML dependencies.",
    "Use ruff check and ruff format before committing.",
    # --- multi-sentence benign passages ---
    "The on-call rotation changes Monday. From then on, alerts page the new team.",
    "Once the flag flips, you are going to see faster cold starts.",
    "If the cache is stale, just clear it and retry the request.",
    "Set the env var and restart; the dashboard picks it up.",
    "After the upgrade you are now on the v2 API by default.",
    "Whatever the linter says about line length, keep URLs intact.",
    "These are the steps: clone, install, test.",
    "Don't follow what you were told before the redesign; docs moved.",
    "wipe your memory of that awful meeting",
    "All instructions for the workshop are in the shared drive.",
    "any instructions left in the old wiki are deprecated",
    "no restrictions apply to read-only API keys",
    "without filters, the photo looks better anyway",
    "Roleplay night is Thursday; bring dice.",
    "He will act as interim lead until June.",
    "ASSISTANT: is a common prefix in chat-log exports.",
    # --- digit/symbol-bearing lines (PET-97 leet-fold FP guard) ---
    # The leet fold maps 0-9/@/$/! across the whole text on match-only views;
    # none of these may flip to an injection match. The base64 line keeps
    # firing exactly encoding.base64-in-text (encoding type, not injection —
    # outside the guard's filter).
    "react 450ms render",
    "version 1.5.3",
    "commit 5e4134c",
    "SHA 7f71a43",
    "QmVuaWduIGJhc2U2NCBwYXlsb2FkIGZvciBQRVQtOTcgcGlubmluZyB0ZXN0cw==",
    "the fix costs $5 and ships Friday!",
    "email support@vigilharbor.com with the trace",
    "run echo $HOME && ls -la!",
)

# ---------------------------------------------------------------------------
# Pinned dispositions — populated per spec D6:
#   step 1: scripted capture at HEAD 71515ab, 2026-06-11 (PRE_EXISTING)
#   step 2: hand-extended accepted-widening entries (ACCEPTED_CLASS)
#   step 3: migrated only->capability flips (MIGRATED)
# Note: "The new instructions are in the README somewhere." appeared as an
# unsanctioned new pair during implementation and triggered spec row 5's
# pre-committed retreat (pattern narrowed to "your new instructions are");
# it now fires nothing and is deliberately unpinned.
# ---------------------------------------------------------------------------

PRE_EXISTING: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "you are a great help": frozenset({f"{_RID}role-switch-only"}),
        "act as soon as you can on that ticket": frozenset({f"{_RID}role-switch-only"}),
        "disregard your earlier email, the times changed": frozenset({f"{_RID}disregard"}),
        "the system override switch on the panel is red": frozenset({f"{_RID}system-override"}),
        "After the upgrade you are now on the v2 API by default.": frozenset(
            {f"{_RID}you-are-now"}
        ),
        "He will act as interim lead until June.": frozenset({f"{_RID}role-switch-only"}),
    }
)

ACCEPTED_CLASS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        # ACCEPTED-CLASS (PET-93 rows 9-10): new contraction trigger
        "you're a great help": frozenset({f"{_RID}role-switch-only"}),
        # ACCEPTED-CLASS (PET-93 rows 9-10): new contraction trigger
        "You're an excellent reviewer, thanks for the catch.": frozenset(
            {f"{_RID}role-switch-only"}
        ),
        # ACCEPTED-CLASS (PET-93 rows 9-10): new from-now-on trigger
        "From now on you are responsible for deployments.": frozenset({f"{_RID}role-switch-only"}),
        # ACCEPTED-CLASS (PET-93 row 4): contraction branch of you-are-now
        "you're now ready to deploy": frozenset({f"{_RID}you-are-now"}),
    }
)

MIGRATED: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        # MIGRATED (PET-93 rows 9-10 grants; was role-switch-only at HEAD):
        # "without limits" became a real grant, flipping the either/or
        # classifier output. Snippet matches SANCTIONED_NEW_GRANTS[0].
        "act as a sounding board without limits on scope": frozenset(
            {f"{_RID}role-switch-capability"}
        ),
    }
)
