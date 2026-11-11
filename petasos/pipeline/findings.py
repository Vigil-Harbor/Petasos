"""Merge findings and preserve policy floors and coverage claims."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from petasos.model import (
    ScanCoverage,
    ScanFinding,
    ScanResult,
    Severity,
    at_least,
    severity_rank,
)
from petasos.scanners.minimal import (
    _ALL_INJECTION_IDS,
    _STRUCTURAL_RULE_IDS,
)

_logger = logging.getLogger("petasos.pipeline")

if TYPE_CHECKING:
    from collections.abc import Sequence

    from petasos.model import Direction, FloorScope

# Lower rank claims less coverage. Two scanners may share a name (Pipeline does not
# require unique names), so a collision keeps the claim that examined the least
# rather than whichever scanner finished last. Every result stays in scanner_results.
_COVERAGE_CLAIM_RANK: dict[str, int] = {
    "error": 0,
    "partial": 1,
    "unsupported": 2,
    "no_targets": 3,
    "complete": 4,
}


def _coverage_claim(coverage: ScanCoverage) -> tuple[int, int, int]:
    return (
        _COVERAGE_CLAIM_RANK[coverage.status],
        coverage.examined_chars,
        coverage.completed_target_count,
    )


def _merge_backend_coverage(
    scanner_results: Sequence[ScanResult],
) -> dict[str, ScanCoverage] | None:
    merged: dict[str, ScanCoverage] = {}
    for r in scanner_results:
        if r.coverage is None:
            continue
        current = merged.get(r.scanner_name)
        if current is None:
            merged[r.scanner_name] = r.coverage
        elif r.coverage != current:
            _logger.debug("duplicate scanner name %s reports differing coverage", r.scanner_name)
            if _coverage_claim(r.coverage) < _coverage_claim(current):
                merged[r.scanner_name] = r.coverage
    return merged or None


_STRUCTURAL_RULE_PREFIX = "petasos.syntactic.structural."
_SELFMOD_RULE_PREFIX = "petasos.selfmod."


def _is_floor_rule(
    rule_id: str,
    direction: Direction = "inbound",
    scope: FloorScope = "all",
) -> bool:
    # Single chokepoint for both floor checks (PET-162 D1). Structural is ALWAYS
    # floor — independent of direction/scope (a different threat class than
    # injection; injection_floor_scope governs the injection family only). The
    # prefix disjunct is a belt-and-suspenders guard kept aligned by a tripwire
    # test (_STRUCTURAL_RULE_IDS <= the structural-prefix set).
    if rule_id in _STRUCTURAL_RULE_IDS or rule_id.startswith(_STRUCTURAL_RULE_PREFIX):
        return True
    if rule_id.startswith(_SELFMOD_RULE_PREFIX):
        return True
    if rule_id in _ALL_INJECTION_IDS:
        # Injection floor is absolute on inbound for every profile (PET-54/124). A
        # profile may relax it for the agent's OWN outbound only by opting into
        # scope="inbound". Every value other than the exact pair
        # (scope=="inbound" AND direction=="outbound") falls through to floor, so
        # an unvalidated scope reaching here (direct construction) fails safe.
        return not (scope == "inbound" and direction == "outbound")
    return False


def _suppress_scanner_findings(
    results: list[ScanResult],
    suppress_rules: frozenset[str],
    direction: Direction = "inbound",
    scope: FloorScope = "all",
) -> list[ScanResult]:
    """Drop findings whose rule_id is suppressed and NOT on the floor, per scanner.

    ``replace(r, findings=kept)`` mutates ONLY ``findings``; ``scanner_name``,
    ``error``, and ``duration_ms`` are preserved, so ``_compute_safe``'s ML-failure
    accounting and the degraded fail-mode block are unaffected (suppression never
    empties an errored result's error). A drop is logged at DEBUG so a later "why
    was nothing flagged?" is a log grep, not a guess — the only runtime trace that
    a profile suppressed a finding.
    """
    out: list[ScanResult] = []
    for r in results:
        kept = tuple(
            f
            for f in r.findings
            if not (
                f.rule_id in suppress_rules and not _is_floor_rule(f.rule_id, direction, scope)
            )
        )
        if len(kept) != len(r.findings):
            dropped = sorted({f.rule_id for f in r.findings} - {f.rule_id for f in kept})
            _logger.debug("profile suppressed %s on scanner %s", dropped, r.scanner_name)
            out.append(replace(r, findings=kept))
        else:
            out.append(r)
    return out


_STANDALONE_TIER3_CRITICAL_COUNT = 3


def _standalone_tier3_check(findings: tuple[ScanFinding, ...]) -> bool:
    critical_count = sum(1 for f in findings if f.severity == Severity.CRITICAL)
    return critical_count >= _STANDALONE_TIER3_CRITICAL_COUNT


def merge_findings(results: Sequence[ScanResult]) -> tuple[ScanFinding, ...]:
    all_findings: list[ScanFinding] = []
    for r in results:
        all_findings.extend(r.findings)

    if not all_findings:
        return ()

    originals: dict[tuple[str, int | None, int | None], ScanFinding] = {}
    positioned: list[ScanFinding] = []
    unpositioned: list[ScanFinding] = []
    for f in all_findings:
        if f.scanner_name == "semgrep" and f.position_basis == "original":
            originals.setdefault(
                (
                    f.rule_id,
                    f.position.start if f.position else None,
                    f.position.end if f.position else None,
                ),
                f,
            )
        elif f.position is not None:
            positioned.append(f)
        else:
            unpositioned.append(f)

    if not positioned:
        return tuple(unpositioned) + tuple(originals.values())

    positioned.sort(key=lambda f: f.position.start)  # type: ignore[union-attr]

    surviving: list[ScanFinding] = []
    current = positioned[0]

    for nxt in positioned[1:]:
        assert current.position is not None
        assert nxt.position is not None
        if nxt.position.start < current.position.end:
            nxt_rank = severity_rank(nxt.severity)
            cur_rank = severity_rank(current.severity)
            if nxt_rank > cur_rank:
                current = nxt
            elif nxt_rank == cur_rank:
                if nxt.confidence > current.confidence:
                    current = nxt
                elif nxt.confidence == current.confidence:
                    surviving.append(current)
                    current = nxt
        else:
            surviving.append(current)
            current = nxt

    surviving.append(current)
    return tuple(surviving) + tuple(unpositioned) + tuple(originals.values())


def _compute_safe(
    findings: tuple[ScanFinding, ...],
    scanner_results: Sequence[ScanResult],
    fail_mode: str,
) -> bool:
    if fail_mode not in ("open", "closed", "degraded"):
        _logger.warning("fail_mode %r is invalid, falling back to 'degraded'", fail_mode)
        fail_mode = "degraded"
    safe = True
    for f in findings:
        if at_least(f.severity, Severity.HIGH):
            safe = False
            break

    syntactic_error = False
    ml_total = 0
    ml_errored = 0
    for r in scanner_results:
        if r.scanner_name == "minimal":
            if r.error is not None:
                syntactic_error = True
            continue
        ml_total += 1
        if r.error is not None:
            ml_errored += 1

    if syntactic_error and fail_mode in ("degraded", "closed"):
        safe = False

    if ml_total == 0:
        return safe

    partial_failure = 0 < ml_errored < ml_total
    all_ml_failure = ml_errored == ml_total

    if fail_mode == "degraded":
        if partial_failure or all_ml_failure:
            safe = False
    elif fail_mode == "open":
        pass
    elif fail_mode == "closed" and (partial_failure or all_ml_failure):
        safe = False

    return safe
