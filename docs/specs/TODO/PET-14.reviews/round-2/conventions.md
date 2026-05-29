# Conventions Review — round 2

## Closure of round 1 findings
- conventions F-1 (single-source tension, P3) — **CLOSED**: security-assertions.md declared canonical; ledger "derived".
- conventions F-2 (missing Deferred trailer, P4) — **CLOSED**: `## Deferred (P2+)` present, correct ordering, matches PET-10/PET-11 style.
- conventions F-3/4/5/6 — **CLOSED** (informational, re-verified).
- correctness F-1/2/3/4 — **CLOSED** (anchors fixed; Plane folded to Deferred).
- edge-cases F-1/2/3/4/5 — **CLOSED** (PIPE-08/09/10, three-tag D2, staleness, seed-closure, SCAN-07).

## Findings
No findings.

Verification:
1. Three-tag model internally consistent across all 4 reference sites (D2, Deliverable 3 render rule, ledger sort, Test plan) — "Suspected-gap → Held* → Held" verbatim. Remaining bare-Held rows (SCAN-01, LIC-05, PROF-01) carry clarifying, non-material notes.
2. Section ordering matches house style exactly (Goal/Scope/Decisions/Design/Test plan/Test command/Done when/Deferred/Out of scope).
3. No premature abstraction/bloat — +4 assertions are minimal falsifiable rows in existing tables; deliverable count unchanged at 5.
4. Invariant fidelity re-verified against source: "Pipeline never throws" (PIPE-01), "Tier 3 cannot be disabled" (CFG-04/ESC-01 Held* nuance, not contradiction), "Frozen exports" (CFG-01/TYP shallow-freeze consistent with PET-10 Deferred), "Fail-mode degraded" (PIPE-02). No mis-statement.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 0 | P4: 0

STATUS: GREEN
