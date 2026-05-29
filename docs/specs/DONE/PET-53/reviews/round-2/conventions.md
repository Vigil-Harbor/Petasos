# Conventions Review -- round 2

## Closure of round 1 findings

All round 1 findings CLOSED. Public properties added (F-1), error format includes type name (F-2), return-value pattern documented as spec-level addition in D2 (F-3), clearing moved to top (F-4), dead _NONE_SENTINEL removed (F-5), post-merge wiki acknowledged (F-6), conftest clarified (F-7).

## Findings

### F-1: Logging call style — `_logger.error(exc_info=True)` vs `_logger.exception()`
**Severity:** P4
audit.py introduces `_logger.error(..., exc_info=True)` while alerting.py keeps `_logger.exception()`. Functionally equivalent but inconsistent style.

### F-2: D4 tracker cap formula is a spec-level addition
**Severity:** P3
Brief says `2 * capacity`; spec changes to `max(2 * capacity, burst_count)`. Category (c) addition with rationale in D4. Sound.

### F-3: D6 logger addition is a spec-level addition
**Severity:** P3
Brief doesn't mention logger; spec adds it as necessary for D2's logging. Category (c).

### F-4: Hook-level error format doesn't include type name
**Severity:** P4
Pre-existing `f"audit hook: {exc}"` at Stages 10-11. Not a spec defect — out of scope.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 2 | P4: 2

STATUS: GREEN
