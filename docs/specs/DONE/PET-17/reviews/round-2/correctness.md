# Correctness Review -- round 2

## Closure of round 1 findings
All R1 findings CLOSED. See closure table in full agent output.

## Findings

### F-1: Cross-field validation breaks two additional existing tests not mentioned in spec
**Severity:** P1
**Where:** spec section 5 "Existing test adjustments"
**Why this is wrong:** `test_tier3_bypasses_per_minute_cap` (L430) and `test_rate_limited_count_reflects_caps` (L538) both use `alert_per_minute_cap=1`, violating `cap(2) >= per_minute_cap(1)`.
**Suggested fix:** List ALL tests affected by the cross-field validation.

### F-2: Cross-field validation makes `per_minute_cap=1` impossible
**Severity:** P1
**Where:** spec lines 91-95
**Why this is wrong:** With strict `<`, minimum valid `per_session_contribution_cap` is 1, which is not `< 1`.
**Suggested fix:** Change to `>` (allow equality, reject only strictly greater). `cap == per_minute_cap` is a degenerate no-op but not broken.

## Summary
P0: 0 | P1: 2 | P2: 0 | P3: 0 | P4: 0

STATUS: RED P0=0 P1=2 P2=0 P3=0 P4=0
