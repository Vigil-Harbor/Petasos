# Edge-Cases Review -- round 2

## Closure of round 1 findings

All P1 findings CLOSED: `recent_sessions` NameError fixed (full L301-321 replaced with `distinct_count`), tracker cap formula changed to `max(2*cap, burst_count)`.
P2 findings CLOSED: `_last_callback_error` clearing moved to top of emit(), private attribute access replaced with public properties.
P3 findings: F-6 (concurrency) CLOSED (documented in D2), F-7 (callback=None) and F-8 (TTL mismatch) PARTIAL — acceptable gaps.
Edge-cases F-4 (SystemExit/CancelledError tests): PARTIAL — KeyboardInterrupt covers the mechanism but named types from D1 not individually tested.

## Findings

### F-1: Test 12 tracker cap assertion is approximate after eviction
**Severity:** P2
After cap eviction, `distinct_count` is an approximation (most recent N sessions). Test description doesn't note this.

### F-2: `test_stale_session_pruning` rewrite lacks concrete code
**Severity:** P2
Spec describes intent but doesn't provide replacement test code. Implementer must infer that `time.monotonic` patching is no longer needed.

### F-3: `_cross_session_tracker` insertion before stale pruning — ordering safe
**Severity:** P3
Non-issue: insert overwrites stale timestamp with `now`, subsequent prune skips it. Correct behavior.

### F-4: `str(exc)` truthiness edge cases
**Severity:** P3
`str(BaseException(0))` returns "0" (truthy), `str(BaseException(None))` returns "None" (truthy). Acceptable behavior.

### F-5: `_global_sequence` integer overflow
**Severity:** P4
Non-issue: Python integers are unbounded.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 2 | P4: 1

STATUS: GREEN
