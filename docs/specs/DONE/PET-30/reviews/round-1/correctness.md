# PET-30 Correctness Review — Round 1

## Findings

### F-1: Spec line number anchors for `__init__` insertion point are off by one
**Severity:** P2
**Where:** spec section "1. Tombstone data structure" (line 60)
**Claim:** "Add to `FrequencyTracker.__init__()` after L85"
L85 is the last line of `__init__()` body. Insertion point is technically correct but could say "at L86" for precision.
**Suggested fix:** Say "after L85 (end of `__init__`)" or "at L86".

### F-2: Spec section 2 cites "after L184" but `get_state()` ends at L184
**Severity:** P2
**Where:** spec section "2. `is_terminated()` public method" (line 73)
The next available insertion point is after L185 (blank line). Intent is clear.

### F-3: `_evict_one()` still preferentially evicts terminated sessions — not addressed
**Severity:** P3
**Where:** spec section "Files to leave alone"; actual code at `frequency.py:211-228`
The brief calls out `_evict_one()` but the spec doesn't mention it. With tombstones, this preferential eviction is benign but should be noted.

### F-4: Test file location diverges from brief for unit tests
**Severity:** P4
Spec correctly adapts to project's actual flat test layout. Enhancement, not defect.

### F-5: Spec's `_derive_tier` proposed code has a redundant `state.terminated` check
**Severity:** P4
Documented as "belt-and-suspenders" in spec. Intentional redundancy.

### F-6: Spec does not address `update()` inbound path for tombstoned sessions
**Severity:** P3
`update()` can re-create a fresh SessionState for a tombstoned session. Guard still blocks, but `FrequencyUpdateResult` is inconsistent.

### F-7: Brief says "All 9 tests" but spec says "All 16 tests"
**Severity:** P4
Spec provides 16 tests (superset of brief's 9). Enhancement.

### F-8: Config validation follows stricter bool guard pattern
**Severity:** P4
Follows the better (alerting-era) pattern. No issue.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 2 | P4: 4

STATUS: GREEN
