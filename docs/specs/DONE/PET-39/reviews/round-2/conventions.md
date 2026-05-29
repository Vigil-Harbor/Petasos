# Conventions Review -- round 2

## Closure of round 1 findings
All 8 round 1 findings CLOSED with evidence.

## Findings

### F-1: Test command mypy scope diverges from ruff scope
**Severity:** P3
mypy scoped to touched files, ruff runs whole-project. Established pattern across prior specs.

### F-2: Decision 2 ("standard" tier) is category-c addition
**Severity:** P3
Well-documented addition with rationale.

### F-3: Decision 5 (isfinite + negative check) is category-c addition
**Severity:** P3
Motivated by edge-cases round-1 F-2.

### F-4: Decision 3 (tier=None behavioral change) is category-c addition
**Severity:** P3
Necessary to close gap; existing test update specified.

### F-5: Deferred section is thorough
**Severity:** P4
Positive observation — four items with rationale.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 4 | P4: 1

STATUS: GREEN
