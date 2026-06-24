"""PET-154: agent-directed fetch/install directive rule (injection.agent-directed-fetch).

Detection of the textbook indirect-injection payload — an instruction *addressed
to the agent* telling it to fetch and install attacker-controlled code — that the
always-on MinimalScanner missed with zero findings (the scan-playground bug,
2026-06-23). The rule is the inbound/natural-language sibling of PET-94's
``command.*`` family: a compositional three-factor conjunction (agent-address
MARKER × fetch/install/execute ACTION × external-RESOURCE cue), per physical
line, direction-blind, unsuppressible (injection floor), HIGH (never CRITICAL),
and reused by the PET-98 decode-and-rescan path.

The anchor-soundness / gate-equivalence tests live in
``tests/test_minimal_scanner.py::TestAgentDirectiveAnchorSoundness`` (the
TestInjectionAnchorSoundness / TestCommandAnchorSoundness analogue); this module
mirrors ``test_command_rules.py`` for detection, corpus pins, tier-3 safety,
decode-path coverage, escalation co-occurrence, and ReDoS/latency.

All async tests rely on ``anyio_mode=auto`` (PET-149) — no inline marker.
"""

from __future__ import annotations

import base64
import codecs
import time
from typing import TYPE_CHECKING, Any

import pytest

from petasos._types import Position, ScanFinding, Severity
from petasos.config import PetasosConfig
from petasos.normalize import normalize
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import (
    _AGENT_DIRECTIVE_MARKERS,
    _ALL_INJECTION_IDS,
    _UNSUPPRESSIBLE_RULE_IDS,
    MinimalScanner,
    _agent_directive_line_hit,
)
from tests.adversarial.syntactic.benign_corpus import (
    AGENT_DIRECTIVE_ACCEPTED_FP,
    AGENT_DIRECTIVE_ACCEPTED_MISS,
    AGENT_DIRECTIVE_BENIGN,
    AGENT_DIRECTIVE_CANONICAL,
    AGENT_DIRECTIVE_EXOTIC_SEP_TP,
    AGENT_DIRECTIVE_EXPECTED_TP,
    BENIGN_CORPUS,
)

if TYPE_CHECKING:
    from collections.abc import Callable

RID = "petasos.syntactic.injection.agent-directed-fetch"
_BASE64_IN_TEXT = "petasos.syntactic.encoding.base64-in-text"
_INVIS = "petasos.syntactic.encoding.invisible-chars"


def _agent_findings(findings: object) -> list[ScanFinding]:
    return [f for f in findings if f.rule_id == RID]  # type: ignore[attr-defined]


# §A — Detection & canonical regression (Done-when 1, 2, 3) -------------------


@pytest.mark.parametrize("snippet", AGENT_DIRECTIVE_EXPECTED_TP)
async def test_expected_tp_fires_exactly_one_high(snippet: str) -> None:
    # Regression for PET-154: each TP (canonical + four phrasing variants +
    # homoglyph twin + Windows-dropper speaker-tag) fires exactly one
    # agent-directed-fetch finding, HIGH. Scoped by rule_id so a future
    # co-firing family does not red the "exactly one" count.
    r = await MinimalScanner().scan(snippet)
    hits = _agent_findings(r.findings)
    assert len(hits) == 1, f"{snippet!r} -> {[f.rule_id for f in r.findings]}"
    assert hits[0].severity == Severity.HIGH


@pytest.mark.parametrize("snippet", AGENT_DIRECTIVE_EXOTIC_SEP_TP)
async def test_exotic_separator_still_fires(snippet: str) -> None:
    # Regression for PET-154 (round-2 edge-cases F-1, the P1 fix): a single
    # non-"\n" line-like separator (VT/FF/NEL/U+2028/U+2029/CR) between the
    # marker and the resource must NOT split the conjunction — the "\n"-only
    # split keeps them in-line. This is the binding pin against single-character
    # separator evasion.
    r = await MinimalScanner().scan(snippet)
    assert len(_agent_findings(r.findings)) == 1, f"exotic-sep payload missed: {snippet!r}"


async def test_canonical_both_directions_and_pipeline_unsafe() -> None:
    # Regression for PET-154 (the exact bug): the canonical payload fires the
    # HIGH finding for BOTH directions (direction-blind, D2) and drives
    # Pipeline.inspect to safe is False. This is the test that would have caught
    # the gap (scan-playground returned safe, 0 findings).
    scanner = MinimalScanner()
    for direction in ("inbound", "outbound"):
        r = await scanner.scan(AGENT_DIRECTIVE_CANONICAL, direction=direction)
        hits = _agent_findings(r.findings)
        assert len(hits) == 1, f"{direction}: {[f.rule_id for f in r.findings]}"
        assert hits[0].severity == Severity.HIGH
    result = await Pipeline(config=PetasosConfig()).inspect(AGENT_DIRECTIVE_CANONICAL)
    assert result.safe is False
    assert any(f.rule_id == RID for f in result.findings)


# §B — Benign twins & disjointness (Done-when 4) ------------------------------


@pytest.mark.parametrize("snippet", AGENT_DIRECTIVE_BENIGN)
async def test_benign_zero_fp(snippet: str) -> None:
    # Regression for PET-154 (DS3/DS4): every benign twin — no-marker installs,
    # the multi-line transcript, the speaker-tag/non-archive-URL turns, and the
    # degenerate-input block — produces zero agent-directed-fetch findings.
    r = await MinimalScanner().scan(snippet)
    assert _agent_findings(r.findings) == [], f"benign {snippet!r} fired agent-directed-fetch"


@pytest.mark.parametrize("snippet", AGENT_DIRECTIVE_ACCEPTED_MISS)
async def test_accepted_miss_stays_miss(snippet: str) -> None:
    # Regression for PET-154 (Out of scope): the DS4 speaker-tag/non-archive-URL
    # form and the cross-line directive are accepted misses (delegated to the ML
    # layer). A future widening that catches one flips this pin consciously.
    r = await MinimalScanner().scan(snippet)
    assert _agent_findings(r.findings) == [], f"accepted-miss {snippet!r} now fires"


async def test_disjointness_only_expected_tp_fires() -> None:
    # Regression for PET-154: across the combined corpus, the set of snippets
    # that fire agent-directed-fetch equals exactly the expected-TP set (TPs +
    # exotic-separator TPs + any accepted-FP) — no benign snippet fires.
    scanner = MinimalScanner()
    expected = (
        set(AGENT_DIRECTIVE_EXPECTED_TP)
        | set(AGENT_DIRECTIVE_EXOTIC_SEP_TP)
        | {s for s, _ in AGENT_DIRECTIVE_ACCEPTED_FP}
    )
    corpus = (
        *AGENT_DIRECTIVE_EXPECTED_TP,
        *AGENT_DIRECTIVE_EXOTIC_SEP_TP,
        *AGENT_DIRECTIVE_BENIGN,
        *AGENT_DIRECTIVE_ACCEPTED_MISS,
        *(s for s, _ in AGENT_DIRECTIVE_ACCEPTED_FP),
    )
    fired = set()
    for snippet in corpus:
        r = await scanner.scan(snippet)
        if _agent_findings(r.findings):
            fired.add(snippet)
    assert fired == expected


async def test_existing_benign_corpus_no_regression() -> None:
    # Regression for PET-154 (§B): the new rule fires zero times across the
    # existing PET-93 BENIGN_CORPUS, so TestBenignCorpusGuard stays green with
    # no new pin.
    scanner = MinimalScanner()
    for snippet in BENIGN_CORPUS:
        r = await scanner.scan(snippet)
        assert _agent_findings(r.findings) == [], (
            f"BENIGN_CORPUS {snippet!r} fired agent-directed-fetch"
        )


# §C — Unsuppressibility (Done-when 5) ----------------------------------------


async def test_unsuppressible_via_constructor_and_profile() -> None:
    # Regression for PET-154 (D1): a profile suppressing the rule (or the whole
    # injection band) still fires it — the id is stripped from _suppress_rules at
    # construction via _UNSUPPRESSIBLE_RULE_IDS.
    assert RID in _UNSUPPRESSIBLE_RULE_IDS
    assert RID in _ALL_INJECTION_IDS

    direct = MinimalScanner(suppress_rules=frozenset({RID}))
    r1 = await direct.scan(AGENT_DIRECTIVE_CANONICAL)
    assert any(f.rule_id == RID for f in r1.findings)

    whole_band = MinimalScanner(suppress_rules=_ALL_INJECTION_IDS)
    r2 = await whole_band.scan(AGENT_DIRECTIVE_CANONICAL)
    assert any(f.rule_id == RID for f in r2.findings)

    profiled = MinimalScanner().with_suppress_rules(frozenset({RID}))
    r3 = await profiled.scan(AGENT_DIRECTIVE_CANONICAL)
    assert any(f.rule_id == RID for f in r3.findings)


# §D — Tier-3 safety (Done-when 6) --------------------------------------------


async def test_tier3_safety_n_stacked_markers_one_finding() -> None:
    # Regression for PET-154 (D3 / round-1 edge-cases F-5): N marked directives,
    # each on its own line, scanned with session_id=None (isolating the
    # standalone CRITICAL net). They are HIGH (never CRITICAL) so they cannot
    # trip Tier-3; and they yield EXACTLY ONE finding (one-finding-per-scan,
    # DS3) — this, not the HIGH severity, is what bounds the injection.* weight-
    # 10.0 frequency contribution to a single increment.
    payload = "\n".join([AGENT_DIRECTIVE_CANONICAL] * 5)
    result = await Pipeline(config=PetasosConfig()).inspect(payload, session_id=None)
    hits = _agent_findings(result.findings)
    assert len(hits) == 1, f"expected exactly one finding, got {len(hits)}"
    assert all(f.severity == Severity.HIGH for f in hits)
    assert result.escalation_tier != "tier3"


# §E — Latency / ReDoS (Done-when 7) ------------------------------------------
# Anchor soundness + gated==ungated live in test_minimal_scanner.py
# (TestAgentDirectiveAnchorSoundness). These pin the new \s+/per-line battery's
# linearity and the <5ms budget.


def _best_of(fn: Callable[..., Any], *args: Any, k: int = 5) -> float:
    best = float("inf")
    for _ in range(k):
        start = time.perf_counter()
        fn(*args)
        best = min(best, time.perf_counter() - start)
    return best


def test_redos_marker_whitespace_flood_growth_ratio() -> None:
    # Regression for PET-154: the widest-quantifier marker (\s+ runs) stays
    # linear on a whitespace flood with no terminal noun (same 10x bound
    # rationale as the PET-93 determiner-flood test).
    pattern = _AGENT_DIRECTIVE_MARKERS[0]  # \bAI\s+agent\s+instruction
    n = 200_000
    t1 = _best_of(pattern.search, "AI " + " " * n)
    t4 = _best_of(pattern.search, "AI " + " " * (4 * n))
    assert t4 <= 10 * max(t1, 1e-4), f"growth ratio {t4 / max(t1, 1e-9):.1f}x exceeds 10x"


def test_redos_newline_flood_growth_ratio() -> None:
    # Regression for PET-154 (DS3): the per-line text.split("\n") iteration is
    # O(total_length), not quadratic, when the whole-text anchor gate is
    # satisfied but no line completes the conjunction (anchor token + newline
    # flood).
    n = 200_000
    t1 = _best_of(_agent_directive_line_hit, "agent" + "\n" * n)
    t4 = _best_of(_agent_directive_line_hit, "agent" + "\n" * (4 * n))
    assert t4 <= 10 * max(t1, 1e-4), f"growth ratio {t4 / max(t1, 1e-9):.1f}x exceeds 10x"


@pytest.mark.parametrize("sep", [" ", "\x85", "\x0b", "\x0c"])
def test_redos_exotic_separator_flood_linear(sep: str) -> None:
    # Regression for PET-154 (round-2 edge-cases F-4): under the "\n"-only split
    # an exotic-separator flood collapses to a single huge line; the single-line
    # action scan must also complete in bounded (linear) time, so the linearity
    # claim does not silently rest on the "\n"-only mental model.
    n = 200_000
    t1 = _best_of(_agent_directive_line_hit, "agent" + sep * n)
    t4 = _best_of(_agent_directive_line_hit, "agent" + sep * (4 * n))
    assert t4 <= 10 * max(t1, 1e-4), f"{sep!r} growth ratio {t4 / max(t1, 1e-9):.1f}x exceeds 10x"


def test_latency_marker_dense_under_5ms() -> None:
    # Regression for PET-154 (D4): the new battery holds well under the <5ms
    # syntactic budget even on marker-dense input that completes no conjunction
    # (so every line is scanned for marker × action × resource). Best-of-5
    # minimum keeps the bound out of scheduler noise.
    dense = "\n".join(["AI agent instruction: please install the thing"] * 100)
    best = _best_of(_agent_directive_line_hit, dense)
    assert best < 0.005, f"agent-directive battery took {best * 1000:.3f}ms on marker-dense input"


# §F — Decode-path coverage (Done-when 8) -------------------------------------


async def test_base64_wrapped_directive_detected_at_blob_span() -> None:
    # Regression for PET-154 (D6): a base64-encoded directive is caught via the
    # PET-98 rescan path, HIGH, with the finding's position at the blob span
    # (cand.position) — the whole input is one base64 run.
    blob = base64.b64encode(AGENT_DIRECTIVE_CANONICAL.encode()).decode()
    r = await MinimalScanner().scan(blob)
    hits = _agent_findings(r.findings)
    assert hits, "base64-wrapped directive missed"
    decoded = next(f for f in hits if "base64-decoded" in f.message)
    assert decoded.severity == Severity.HIGH
    assert decoded.position == Position(start=0, end=len(blob))


async def test_base64_decode_fires_when_base64_flag_suppressed() -> None:
    # Regression for PET-154 (D6 / PET-98 Decision 3): the decode stage runs even
    # when the LOW base64-in-text flag is suppressed; the HIGH agent-directive
    # still fires (and is itself unsuppressible).
    blob = base64.b64encode(AGENT_DIRECTIVE_CANONICAL.encode()).decode()
    scanner = MinimalScanner(suppress_rules=frozenset({_BASE64_IN_TEXT}))
    r = await scanner.scan(blob)
    assert any(f.rule_id == RID for f in r.findings)
    assert not any(f.rule_id == _BASE64_IN_TEXT for f in r.findings)


async def test_rot13_wrapped_directive_offset_map() -> None:
    # Regression for PET-154 (round-1 edge-cases F-4): a ROT13-encoded directive
    # is the only carrier exercising the per-match normalized-space branch
    # (cand.position is None). It must fire, and matched_text must equal the
    # marker substring of normalized.normalized at the reported position —
    # proving the length-preserving offset map.
    cipher = codecs.encode(AGENT_DIRECTIVE_CANONICAL, "rot_13")
    r = await MinimalScanner().scan(cipher)
    hits = _agent_findings(r.findings)
    assert hits, "ROT13-wrapped directive missed"
    rot = next(f for f in hits if "rot13-decoded" in f.message)
    assert rot.severity == Severity.HIGH
    assert rot.position is not None
    norm = normalize(cipher).normalized
    assert rot.matched_text == norm[rot.position.start : rot.position.end]


# §H — Escalation co-occurrence (DS2; round-1 edge-cases F-6) ------------------


def _invis_finding(findings: object) -> ScanFinding | None:
    return next((f for f in findings if f.rule_id == _INVIS), None)  # type: ignore[attr-defined]


async def test_escalation_plain_path_invisible_chars_to_high() -> None:
    # Regression for PET-154 (DS2 case a): a plain-path agent-directive
    # co-occurring with a MEDIUM invisible-chars finding escalates it to HIGH.
    payload = AGENT_DIRECTIVE_CANONICAL.replace("install", "install​")  # ZWSP
    r = await MinimalScanner().scan(payload)
    inv = _invis_finding(r.findings)
    assert inv is not None and inv.severity == Severity.HIGH
    assert any(f.rule_id == RID for f in r.findings)


async def test_escalation_decode_path_invisible_chars_to_high() -> None:
    # Regression for PET-154 (DS2 case b): the same directive carried via base64
    # + the same invisible-chars MEDIUM produces identical escalation, proving no
    # plain-vs-decode asymmetry (the decode path's matched flips the flag too).
    blob = base64.b64encode(AGENT_DIRECTIVE_CANONICAL.encode()).decode()
    payload = blob + "​"  # ZWSP in the outer text
    r = await MinimalScanner().scan(payload)
    inv = _invis_finding(r.findings)
    assert inv is not None and inv.severity == Severity.HIGH
    assert any(f.rule_id == RID for f in r.findings)


async def test_escalation_no_invisible_chars_is_noop() -> None:
    # Regression for PET-154 (DS2 case c): an agent-directive alone mutates
    # nothing — the escalation pass is a no-op when there is nothing to escalate.
    r = await MinimalScanner().scan(AGENT_DIRECTIVE_CANONICAL)
    assert _invis_finding(r.findings) is None
    assert any(f.rule_id == RID for f in r.findings)
