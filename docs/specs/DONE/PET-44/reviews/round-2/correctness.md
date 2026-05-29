# Correctness Review -- round 2

## Closure of round 1 findings

All round 1 findings closed.

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | Micro sign dead code | CLOSED | D3 note: key must be U+03BC; code block line 176 uses U+03BC |
| F-2 | Test #2 infeasible | CLOSED | Reframed as _is_strippable() direct filter test; D1 confirms no BMP Cf reaches step 4 |
| F-3 | D3 count mismatch | CLOSED | D3 table, code block, and summary all show 44 |
| F-4 | Cosmetic categorization | CLOSED | P4, no action needed |

## Findings

### F-1: Adversarial test #21 describes pipeline-level re-strip behavior that cannot occur (P2)
Same infeasibility as original test #2. Test #2 was reframed as wiring test but test #21 was not. Fix: reframe similarly.

## Summary
P0: 0 | P1: 0 | P2: 1

STATUS: GREEN
