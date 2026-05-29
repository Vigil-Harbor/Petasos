# Conventions Review — PET-75 Round 2

## Closure of round 1 findings
All 23 round 1 findings across 3 lenses CLOSED with evidence.

## Findings

### F-1: `__init__.py` for escalation test dir — only `frequency/` has one (outlier)
**Severity:** P4
Harmless. Including it is fine for forward consistency.

### F-2: Brief criterion `tier == "rate_limited"` deliberately changed (category c)
**Severity:** P3
Decision 4 changes with explicit rationale. Flagging for human drift-check.

### F-3: Brief benchmark criterion moved to Out-of-scope (category c)
**Severity:** P3
Functional behavior still tested; only benchmark assertion deferred.

### F-4: Hardcoded threshold vs brief "configurable" (category c)
**Severity:** P3
Decision 1 has rationale. Already flagged in round 1.

### F-5: `derive_tier()` NaN fail-closed is new behavior (category c)
**Severity:** P3
Defensively correct. Flagging for human acknowledgment.

### F-6: `_compact_ttl_deque` doesn't sort rebuilt deque
**Severity:** P2
Same root as correctness/edge-cases finding. Eviction loop invariant depends on sorted order.

### F-7: Line numbers accurate but fragile
**Severity:** P4

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 4 | P4: 2

STATUS: GREEN
