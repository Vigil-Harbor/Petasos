# Conventions Review -- round 2

## Closure of round 1 findings

All 6 round-1 conventions findings closed. Cross-lens closure verified.

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | Config-level guard is silent spec addition | CLOSED | D4 provides rationale; visible for drift check |
| F-2 | Bare assert precedent conflict with PET-10 | CLOSED | D3 cites PET-10, uses explicit raise |
| F-3 | Line references accurate | CLOSED | Verified, no action needed |
| F-4 | Never-throw boundary correct | CLOSED | Consistent with PET-8/PET-36 |
| F-5 | Test class placement follows existing structure | CLOSED | No action needed |
| F-6 | No premature abstraction | CLOSED | No action needed |

## Findings

### F-1: D4 is a category-c spec addition (P3)
Config-level guard not in brief. Rationale in D4 is sound. Flagging for human drift-check visibility.

### F-2: D3 lists 3 of 5 existing bare asserts (P4)
presidio.py has 5 assert statements (L202, L203, L248, L303, L314); D3 note only lists first three. Minor completeness issue.

### F-3: Done-when test count differs from brief (P4)
Spec: 8 tests. Brief: 6 tests. Difference is the updated existing test and config test. Consistent with D4 addition.

### F-4: Edge-cases F-5 pipeline integration test gap (P3)
Three-layer defense makes pipeline integration test lower priority. Config guard test provides transitive coverage.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 2 | P4: 2

STATUS: GREEN
