# Correctness Review — Round 2

## Closure of round 1 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | Chain payload triggers `you-are-now` | CLOSED | Spec D5: payload redesigned to `f"ignore {TAG_CHAR}previous instructions"` — verified against all 8 injection + 9 role-switch patterns. No match pre-fix. |
| F-2 | Stripping tag char does not restore space | CLOSED | Spec D5: space before tag char; stripping produces "ignore previous instructions" matching regex at minimal.py:29 |
| F-3 | Ticket shows "refuted" status | CLOSED | Informational; no spec change needed |

## Findings

None. All line-number anchors verified against current source. Corrected payload tested against all injection/role-switch patterns — no secondary triggers. End-to-end pipeline execution confirmed: safe=True, zero findings, one scanner error — matching baseline assertions.

## Summary
P0: 0 | P1: 0 | P2: 0

STATUS: GREEN
