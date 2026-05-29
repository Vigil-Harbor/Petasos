# Conventions Review — Round 3

## Closure of round 2 findings

All 6 round-2 conventions findings CLOSED.

## Findings

### F-1: Spec references `_SEVERITY_RANK` from `pipeline.py` for use in `alerting.py`
**Severity:** P3
**Where:** spec line 178
**Convention violated:** Leading-underscore module-private naming convention
**Suggested fix:** Either define local severity comparison in alerting.py (preferred — small duplication) or promote to public export in _types.py.

### F-2: `AuditEvent` and `Alert` lack `to_dict()` / `from_dict()` methods
**Severity:** P4
**Where:** spec lines 49-58, 63-75
**Convention violated:** Other _types.py dataclasses have serialization methods
**Suggested fix:** None required — brief explicitly excludes built-in serialization (line 149).

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 1 | P4: 1

STATUS: GREEN
