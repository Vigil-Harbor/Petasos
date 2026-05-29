# Edge-Cases Review -- round 3

## Closure of round 2 findings
All R2 P1/P2 findings CLOSED. Memory bound overshoot documented, recovery test added, counter semantics preserved.

## Findings

### F-1: session_minute_deque scoping note (P3)
Maintainability note — the variable assigned at setdefault must only be used on the accept path.

### F-2: _evict_old on empty deque is a no-op (P4)
Consistent with existing pattern; no change needed.

### F-3: Test 2 describes session cap but global cap is what's exhausted (P4)
Descriptive imprecision; assertion is correct.

### F-4: setdefault creates phantom entries for globally-rejected alerts (P2)
Self-healing (empty deques pruned on next _prune_stale). Bounded by memory cap. Note recommended.

### F-5: from_dict/to_dict handle new fields automatically (P2 confirmed non-issue)
No finding — both methods use fields() and work with int defaults.

### F-6: Test 7 assertion may hit 5-key overshoot (P2)
Clarify to trigger _prune_stale before asserting, or assert <= 105.

### F-7: No float-rejection test for new int config fields (P3)
Consistent with existing convention; optional addition.

### F-8: PetasosConfig.copy() works automatically (P4)
Confirmed non-issue.

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 2 | P4: 3

STATUS: GREEN
