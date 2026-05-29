# Edge-Cases Review — PET-75 Round 1

## Findings

### F-1: `tier="rate_limited"` propagates into `escalation_tier` on PipelineResult, poisoning downstream
**Severity:** P1
Rate-limited FrequencyUpdateResult flows through `_premium_escalation_hook` → `escalation_tier = "rate_limited"`. Breaks `_TIER_ACTIONS` KeyError path, pollutes audit trail, triggers unnecessary alerting code paths.

### F-2: Existing test `test_rate_limited_result_is_frozen` asserts `tier == "none"` — will break
**Severity:** P1
`tests/test_frequency.py:475` asserts `RATE_LIMITED_RESULT.tier == "none"`. Spec changes tier to `"rate_limited"` without updating existing tests.

### F-3: TTL deque grows unboundedly for frequently-refreshed sessions
**Severity:** P1
Each update appends new deque entry. 10k sessions × 100 updates = 1M entries. No compaction or bound. Original O(n) scan had O(1) extra space.

### F-4: Standalone tier-3 check placement is after severity overrides — profiles can suppress CRITICAL findings
**Severity:** P1
Stage 5c applies severity overrides which can downgrade CRITICAL to HIGH before the standalone check at Stage 8b. Contradicts spec's claim of firing on "raw scan output."

### F-5: Empty findings tuple handled correctly by sum()
**Severity:** P2
No crash, no corruption. Clarity/documentation gap only.

### F-6: `derive_tier()` does not validate NaN/Inf score
**Severity:** P2
NaN score → all comparisons return False → returns "none" (fail-open in security context). Inherited from existing evaluate_tier().

### F-7: `reset()` and `force_reset()` leave stale deque entries
**Severity:** P2
Stale entries are benign (skipped on eviction) but add to deque bloat.

### F-8: Stage 8b interaction with `"rate_limited"` escalation_tier partially mitigates F-1
**Severity:** P2
Standalone check can override `"rate_limited"` → `"tier3"` but only when >= 3 CRITICAL findings.

### F-9: Brief requires "Pipeline log output distinguishes rate-limited from disabled" — spec has no logging change
**Severity:** P2
Duplicate of correctness F-1.

### F-10: `derive_tier()` not added to `premium/__init__.py` exports
**Severity:** P2
Inconsistent with `evaluate_tier` export pattern.

### F-11: Double-write check on terminated sessions with multiple stale entries is correct but undocumented
**Severity:** P3
First stale entry triggers tombstone/delete; subsequent entries skip. Correct but subtle.

### F-12: Test 15 benchmark assertion `< 1ms` may flake on CI
**Severity:** P3
GC pauses, Windows timer resolution, loaded CI could cause flakes.

## Summary
P0: 0 | P1: 4 | P2: 5 | P3: 2 | P4: 0

STATUS: RED P0=0 P1=4 P2=5 P3=2 P4=0
