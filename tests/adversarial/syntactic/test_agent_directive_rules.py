"""Pin same-line agent directives, precision boundaries and decoded-carrier budgets.

See docs/architecture/rationale.md, "Agent directive boundaries"."""

from __future__ import annotations

import base64
import codecs
import time
from typing import TYPE_CHECKING, Any

import pytest

from petasos.config.sections import PetasosConfig
from petasos.model import Position, ScanFinding, Severity
from petasos.normalize import normalize
from petasos.pipeline import Pipeline
from petasos.scanners.minimal import MinimalScanner
from petasos.scanners.minimal.agent_directive import (
    _AGENT_DIRECTIVE_MARKERS,
    _agent_directive_line_hit,
)
from petasos.scanners.minimal.taxonomy import _ALL_INJECTION_IDS, _UNSUPPRESSIBLE_RULE_IDS
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
    from collections.abc import Callable, Iterable

RID = "petasos.syntactic.injection.agent-directed-fetch"
_BASE64_IN_TEXT = "petasos.syntactic.encoding.base64-in-text"
_INVIS = "petasos.syntactic.encoding.invisible-chars"


def _agent_findings(findings: Iterable[ScanFinding]) -> list[ScanFinding]:
    return [f for f in findings if f.rule_id == RID]


@pytest.mark.parametrize("snippet", AGENT_DIRECTIVE_EXPECTED_TP)
async def test_expected_tp_fires_exactly_one_high(snippet: str) -> None:
    r = await MinimalScanner().scan(snippet)
    hits = _agent_findings(r.findings)
    assert len(hits) == 1, f"{snippet!r} -> {[f.rule_id for f in r.findings]}"
    assert hits[0].severity == Severity.HIGH


@pytest.mark.parametrize("snippet", [s for s, _ in AGENT_DIRECTIVE_ACCEPTED_FP])
async def test_accepted_fp_fires_exactly_one_high(snippet: str) -> None:
    r = await MinimalScanner().scan(snippet)
    hits = _agent_findings(r.findings)
    assert len(hits) == 1, f"{snippet!r} -> {[f.rule_id for f in r.findings]}"
    assert hits[0].severity == Severity.HIGH


def test_accepted_fp_set_is_isolated_case() -> None:
    # See docs/architecture/rationale.md, "Syntactic fixture precision".
    assert len(AGENT_DIRECTIVE_ACCEPTED_FP) <= 1


@pytest.mark.parametrize("snippet", AGENT_DIRECTIVE_EXOTIC_SEP_TP)
async def test_exotic_separator_still_fires(snippet: str) -> None:
    # Only newline splits the conjunction; exotic separators must not become an evasion boundary.
    r = await MinimalScanner().scan(snippet)
    assert len(_agent_findings(r.findings)) == 1, f"exotic-sep payload missed: {snippet!r}"


async def test_canonical_both_directions_and_pipeline_unsafe() -> None:
    scanner = MinimalScanner()
    for direction in ("inbound", "outbound"):
        r = await scanner.scan(AGENT_DIRECTIVE_CANONICAL, direction=direction)
        hits = _agent_findings(r.findings)
        assert len(hits) == 1, f"{direction}: {[f.rule_id for f in r.findings]}"
        assert hits[0].severity == Severity.HIGH
    result = await Pipeline(config=PetasosConfig()).inspect(AGENT_DIRECTIVE_CANONICAL)
    assert result.safe is False
    assert any(f.rule_id == RID for f in result.findings)


async def test_zwsp_separated_conjunction_fires() -> None:
    payload = "\u200b".join(AGENT_DIRECTIVE_CANONICAL.split())
    r = await MinimalScanner().scan(payload)
    hits = _agent_findings(r.findings)
    assert len(hits) == 1
    assert hits[0].severity == Severity.HIGH
    assert hits[0].position is None
    invis = next(
        f for f in r.findings if f.rule_id == "petasos.syntactic.encoding.invisible-chars"
    )
    assert invis.severity == Severity.HIGH


@pytest.mark.parametrize("snippet", AGENT_DIRECTIVE_BENIGN)
async def test_benign_zero_fp(snippet: str) -> None:
    r = await MinimalScanner().scan(snippet)
    assert _agent_findings(r.findings) == [], f"benign {snippet!r} fired agent-directed-fetch"


@pytest.mark.parametrize("snippet", AGENT_DIRECTIVE_ACCEPTED_MISS)
async def test_accepted_miss_stays_miss(snippet: str) -> None:
    r = await MinimalScanner().scan(snippet)
    assert _agent_findings(r.findings) == [], f"accepted-miss {snippet!r} now fires"


async def test_disjointness_only_expected_tp_fires() -> None:
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
    """Pin existing benign corpus preservation."""
    scanner = MinimalScanner()
    for snippet in BENIGN_CORPUS:
        r = await scanner.scan(snippet)
        assert _agent_findings(r.findings) == [], (
            f"BENIGN_CORPUS {snippet!r} fired agent-directed-fetch"
        )


async def test_unsuppressible_via_constructor_and_profile() -> None:
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


async def test_tier3_safety_n_stacked_markers_one_finding() -> None:
    # See docs/architecture/rationale.md, "Decoded finding budgets".
    payload = "\n".join([AGENT_DIRECTIVE_CANONICAL] * 5)
    result = await Pipeline(config=PetasosConfig()).inspect(payload, session_id=None)
    hits = _agent_findings(result.findings)
    assert len(hits) == 1, f"expected exactly one finding, got {len(hits)}"
    assert all(f.severity == Severity.HIGH for f in hits)
    assert result.escalation_tier != "tier3"


async def test_tier3_safety_decoded_carriers_one_finding() -> None:
    # See docs/architecture/rationale.md, "Decoded finding budgets".
    b64 = base64.b64encode(AGENT_DIRECTIVE_CANONICAL.encode()).decode()
    hexed = AGENT_DIRECTIVE_CANONICAL.encode().hex()
    payload = "\n".join([b64] * 3 + [hexed] * 3)
    result = await Pipeline(config=PetasosConfig()).inspect(
        payload, session_id="sess-decoded-carriers"
    )
    hits = _agent_findings(result.findings)
    assert len(hits) == 1, f"expected one decoded agent-directive finding, got {len(hits)}"
    assert hits[0].severity == Severity.HIGH
    assert result.escalation_tier != "tier3"


def _best_of(fn: Callable[..., Any], *args: Any, k: int = 5) -> float:
    best = float("inf")
    for _ in range(k):
        start = time.perf_counter()
        fn(*args)
        best = min(best, time.perf_counter() - start)
    return best


def test_redos_marker_whitespace_flood_growth_ratio() -> None:
    pattern = _AGENT_DIRECTIVE_MARKERS[0]
    n = 200_000
    t1 = _best_of(pattern.search, "AI " + " " * n)
    t4 = _best_of(pattern.search, "AI " + " " * (4 * n))
    assert t4 <= 10 * max(t1, 1e-4), f"growth ratio {t4 / max(t1, 1e-9):.1f}x exceeds 10x"


def test_redos_newline_flood_growth_ratio() -> None:
    n = 200_000
    t1 = _best_of(_agent_directive_line_hit, "agent" + "\n" * n)
    t4 = _best_of(_agent_directive_line_hit, "agent" + "\n" * (4 * n))
    assert t4 <= 10 * max(t1, 1e-4), f"growth ratio {t4 / max(t1, 1e-9):.1f}x exceeds 10x"


@pytest.mark.parametrize("sep", [" ", "\x85", "\x0b", "\x0c"])
def test_redos_exotic_separator_flood_linear(sep: str) -> None:
    n = 200_000
    t1 = _best_of(_agent_directive_line_hit, "agent" + sep * n)
    t4 = _best_of(_agent_directive_line_hit, "agent" + sep * (4 * n))
    assert t4 <= 10 * max(t1, 1e-4), f"{sep!r} growth ratio {t4 / max(t1, 1e-9):.1f}x exceeds 10x"


def test_latency_marker_dense_under_5ms() -> None:
    dense = "\n".join(["AI agent instruction: please install the thing"] * 100)
    best = _best_of(_agent_directive_line_hit, dense)
    assert best < 0.005, f"agent-directive battery took {best * 1000:.3f}ms on marker-dense input"


async def test_base64_wrapped_directive_detected_at_blob_span() -> None:
    blob = base64.b64encode(AGENT_DIRECTIVE_CANONICAL.encode()).decode()
    r = await MinimalScanner().scan(blob)
    hits = _agent_findings(r.findings)
    assert hits, "base64-wrapped directive missed"
    decoded = next(f for f in hits if "base64-decoded" in f.message)
    assert decoded.severity == Severity.HIGH
    assert decoded.position == Position(start=0, end=len(blob))


async def test_base64_wrapped_obfuscated_directive_normalized_before_match() -> None:
    zwsp = chr(0x200B)
    obfuscated = AGENT_DIRECTIVE_CANONICAL.replace("AGENT", "A" + zwsp + "GENT", 1)
    assert zwsp in obfuscated
    blob = base64.b64encode(obfuscated.encode()).decode()
    r = await MinimalScanner().scan(blob)
    hits = _agent_findings(r.findings)
    assert hits, "obfuscated base64-wrapped directive missed — blob branch not normalized"
    decoded = next(f for f in hits if "base64-decoded" in f.message)
    assert decoded.severity == Severity.HIGH
    assert decoded.position == Position(start=0, end=len(blob))


async def test_base64_wrapped_zwsp_separated_directive_detected_at_blob_span() -> None:
    zwsp = chr(0x200B)
    separated = AGENT_DIRECTIVE_CANONICAL.replace(" ", zwsp)
    assert " " not in separated
    blob = base64.b64encode(separated.encode()).decode()
    r = await MinimalScanner().scan(blob)
    hits = _agent_findings(r.findings)
    assert hits, "ZWSP-separated base64-wrapped directive missed"
    decoded = next(f for f in hits if "base64-decoded" in f.message)
    assert decoded.severity == Severity.HIGH
    assert decoded.position == Position(start=0, end=len(blob))


async def test_base64_decode_fires_when_base64_flag_suppressed() -> None:
    blob = base64.b64encode(AGENT_DIRECTIVE_CANONICAL.encode()).decode()
    scanner = MinimalScanner(suppress_rules=frozenset({_BASE64_IN_TEXT}))
    r = await scanner.scan(blob)
    assert any(f.rule_id == RID for f in r.findings)
    assert not any(f.rule_id == _BASE64_IN_TEXT for f in r.findings)


async def test_rot13_wrapped_directive_offset_map() -> None:
    cipher = codecs.encode(AGENT_DIRECTIVE_CANONICAL, "rot_13")
    r = await MinimalScanner().scan(cipher)
    hits = _agent_findings(r.findings)
    assert hits, "ROT13-wrapped directive missed"
    rot = next(f for f in hits if "rot13-decoded" in f.message)
    assert rot.severity == Severity.HIGH
    assert rot.position is not None
    norm = normalize(cipher).normalized
    assert rot.matched_text == norm[rot.position.start : rot.position.end]


def _invis_finding(findings: Iterable[ScanFinding]) -> ScanFinding | None:
    return next((f for f in findings if f.rule_id == _INVIS), None)


async def test_escalation_plain_path_invisible_chars_to_high() -> None:
    payload = AGENT_DIRECTIVE_CANONICAL.replace("install", "install​")
    r = await MinimalScanner().scan(payload)
    inv = _invis_finding(r.findings)
    assert inv is not None and inv.severity == Severity.HIGH
    assert any(f.rule_id == RID for f in r.findings)


async def test_escalation_decode_path_invisible_chars_to_high() -> None:
    blob = base64.b64encode(AGENT_DIRECTIVE_CANONICAL.encode()).decode()
    payload = blob + "​"
    r = await MinimalScanner().scan(payload)
    inv = _invis_finding(r.findings)
    assert inv is not None and inv.severity == Severity.HIGH
    assert any(f.rule_id == RID for f in r.findings)


async def test_escalation_no_invisible_chars_is_noop() -> None:
    r = await MinimalScanner().scan(AGENT_DIRECTIVE_CANONICAL)
    assert _invis_finding(r.findings) is None
    assert any(f.rule_id == RID for f in r.findings)
