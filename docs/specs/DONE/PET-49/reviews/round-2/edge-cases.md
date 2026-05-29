# Edge-Cases Review -- round 2

## Closure of round 1 findings

All round 1 P1 findings CLOSED:
- F-1 (P1): no-comment convention removed, config.py comment added
- F-2 (P1): _HighFindingScanner defined with full implementation

P2 findings CLOSED:
- F-3: CLAUDE.md in scope
- F-4: Single-ML-scanner case covered by all_ml_failure path (advisory)
- F-5: Semantic shift documented

## Findings

### F-1: Test #3 does not uniquely exercise the partial_failure fix
**Severity:** P2
**Where:** spec.md:133
_HighFindingScanner returns HIGH finding which makes safe=False in the findings loop before the fail-mode branch. Test #3 would pass on both old and new code.
**Suggested fix:** Use MEDIUM severity instead of HIGH in _HighFindingScanner, or acknowledge as belt-and-suspenders.

### F-2: config.py line number reference is fragile
**Severity:** P4
Contextual description is sufficient for implementation.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 0 | P4: 1

STATUS: GREEN
