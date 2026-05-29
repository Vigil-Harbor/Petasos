# Edge-Cases Review -- round 2

## Closure of round 1 findings
All R1 findings CLOSED. See closure table in full agent output.

## Findings

### F-1: Memory bound can be overshot by up to 5 keys per evaluate() call
**Severity:** P2
**Where:** spec section 3, lines 128-142
**Note:** Multiple candidates with different rule_ids can each insert a new key. Bounded by O(rules)=5, corrected on next _prune_stale. Add acknowledgment note.

### F-2: session_minute_deque variable scoping across gate and append
**Severity:** P3 (downgraded)
**Note:** Correct Python scoping. Maintenance fragility, not runtime failure. Document coupling.

### F-3/F-4/F-5: Three existing tests broken by cross-field validation (same root cause as correctness F-1)
**Severity:** P1
**Where:** test_per_minute_cap (L361), test_rate_limited_count_reflects_caps (L538), test_tier3_bypasses_per_minute_cap (L430)
**Note:** All use per_minute_cap <= default per_session_contribution_cap(2).

### F-6: No test for memory-bound recovery after natural expiry
**Severity:** P2
**Suggested fix:** Add test: after dict at capacity, advance 61s, verify new session is accepted.

### F-7: Cross-field validation doesn't check per-hour cap relationship
**Severity:** P2
**Note:** Semantically harmless but potentially confusing. Add explanatory note.

### F-8: _session_rate_limited_count merges memory-bound and contribution-cap rejections
**Severity:** P3
**Note:** Acceptable for now. Add acknowledgment.

## Summary
P0: 0 | P1: 3 | P2: 3 | P3: 2 | P4: 0

STATUS: RED P0=0 P1=3 P2=3 P3=2 P4=0
