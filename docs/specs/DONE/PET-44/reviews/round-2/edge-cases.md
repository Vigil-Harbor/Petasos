# Edge-Cases Review -- round 2

## Closure of round 1 findings

All 7 round 1 edge-case findings closed.

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | Micro sign dead code | CLOSED | D3 note; table key U+03BC |
| F-2 | Hangul idempotency | CLOSED | NFC recomposition at spec line 124; Hangul rationale at line 132 |
| F-3 | Counter not updated | CLOSED | stripped_count += restrip_count at line 104 |
| F-4 | Test #2 infeasible | CLOSED | Reframed as wiring test |
| F-5 | No encoding finding for Mn | CLOSED | P3; out of scope implicitly |
| F-6 | Performance regression | CLOSED | Out of scope line 293 |
| F-7 | Greek eta weak confusable | CLOSED | P4; accepted |

## Findings

### F-1: Pipeline gate interaction with D5 — Mn stripping disabled when any toggle off (P2)
D5 says unconditional but pipeline.py skips normalize() entirely when any toggle is off. Document the interaction.

### F-2: guard.py _normalize_tool_name lacks NFD + Mn strip (P2)
Tool name combining mark bypass still possible. Out of scope for this spec but should be flagged.

### F-3: NFC after Mn strip — Mc/Me marks not stripped, no documentation of boundary (P3)
Only Mn stripped, not Mc/Me. No known attack uses these but boundary should be documented.

### F-4: Test #21 infeasible (P3)
Same as correctness R2 F-1. Test #21 not reframed like test #2.

### F-5: No test for NFD-decomposable input with zero Mn marks (P3)
Hangul syllable input should verify no-op branch avoids decomposition artifacts.

### F-7: Standalone combining mark input edge case (P4)
Input of only combining marks → empty normalized string. Correct behavior but untested.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 3 | P4: 1

STATUS: GREEN
