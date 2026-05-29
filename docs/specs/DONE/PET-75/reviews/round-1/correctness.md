# Correctness Review — PET-75 Round 1

## Findings

### F-1: Brief "Done when" criterion about pipeline logging not addressed
**Severity:** P1
Brief explicitly requires "Pipeline log output distinguishes rate-limited from disabled." Spec has no logging change in FREQ-04 section. Done-when list omits this criterion.

### F-2: FREQ-05 deque growth is unbounded for long-lived frequently-updated sessions
**Severity:** P2
Each `update()` appends a new `(expiry, session_id)` entry. Stale entries only cleaned at eviction time. 10k sessions updated 100 times = 1M deque entries. Trades O(n) time for unbounded space.

### F-3: Decision 4 dual-approach creates ambiguity — `"rate_limited"` as tier value breaks implicit closed set
**Severity:** P2
`_TIER_ACTIONS` dict in escalation.py only has keys `"none"`, `"tier1"`, `"tier2"`, `"tier3"`. If `"rate_limited"` tier ever reaches `evaluate_escalation()`, KeyError. Audit trail records non-standard tier value.

### F-4: ESC-03 test 7 proposes verifying `derive_tier()` is "called" without specifying mechanism
**Severity:** P3
Test should verify behavior (correct tier for profile thresholds), not mock internals.

### F-5: Stage 8b escalation_tier override condition is unnecessarily complex
**Severity:** P2
`if escalation_tier is None or escalation_tier != "tier3"` is equivalent to `if escalation_tier != "tier3"`. Also doesn't document the tier1/tier2 override case.

## Summary
P0: 0 | P1: 1 | P2: 3 | P3: 1 | P4: 0

STATUS: RED P0=0 P1=1 P2=3 P3=1 P4=0
