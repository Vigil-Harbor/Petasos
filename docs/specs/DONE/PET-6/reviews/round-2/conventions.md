# PET-6 Spec Review — Conventions (Round 2)

## Closure of round 1 findings

All round 1 findings CLOSED. See closure table in full report.

## Findings

### F-1 (P2): NormalizedText field `.has_rtl_override` — wrong name
**Section:** spec line 144
Actual field is `.rtl_overrides_detected` per `_types.py` line 113. Cross-reference with correctness F-1.

### F-2 (P3): Wiki architecture.md diverges from spec constructor — expected, managed
### F-3 (P3): D7 is spec-level addition with rationale — category (c), sound
### F-4 (P3): D8 is spec-level formalization of brief requirement — category (c)
### F-5 (P3): Early exit in closed mode — brief-authorized, acknowledged in Deferred
### F-6 (P3): **kwargs rejection contradicts brief's risk table recommendation
The brief recommends `**kwargs` for forward compatibility; the spec rejects it for mypy --strict compatibility. Should explicitly acknowledge the deviation.
### F-7 (P4): __all__ export list not specified for new modules
### F-8 (P4): Section numbering "4.x" cosmetic

## Summary

| Severity | Count |
|----------|-------|
| P0 | 0 |
| P1 | 0 |
| P2 | 1 |
| P3 | 5 |
| P4 | 2 |

STATUS: GREEN
