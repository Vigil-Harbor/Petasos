# Edge-Cases Review -- round 3

## Closure table
All round 2 findings CLOSED:
- edge-cases F-1 (get_type_hints crash): CLOSED — spec uses `f.type == "bool"` string comparison, verified empirically
- edge-cases F-2-F-4: CLOSED per evidence in review

## Findings

### F-1: Coverage test fragile if `from __future__ import annotations` removed (P3)
If PEP 649/749 adoption removes the import, `f.type` returns `bool` (type) not `"bool"` (string). Fail-safe direction. Suggested: handle both in test.

### F-2: No test for multiple invalid fields in single from_dict call (P4)
### F-3: numpy.bool_ compatibility — non-issue (P4)

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 1 | P4: 2

STATUS: GREEN
