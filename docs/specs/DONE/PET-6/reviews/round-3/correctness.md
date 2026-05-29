# PET-6 Spec Review — Correctness (Round 3)

## Closure of round 2 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| correctness R2 | F-1 | NormalizedText field `.has_rtl_override` | CLOSED | spec line 144: `.rtl_overrides_detected` matches `_types.py` |
| correctness R2 | F-2 | Premium hook placement contradicts stage ordering | CLOSED | stages 6-7 before fail-mode, 10-11 after anonymize |
| correctness R2 | F-3 | `_scan_one` omits `duration_ms` in error | CLOSED | spec line 161-162: elapsed captured |
| correctness R2 | F-4 | Early exit PipelineResult underspecified | CLOSED | spec line 148: explicit construction |

## Findings

### F-1 (P2): Audit/alert hook signatures require PipelineResult before it is assembled
Stage 10 passes `result: PipelineResult` but assembly is at stage 12. No-ops in PET-6 so no runtime impact. Signatures may change in PET-9.

### F-2 (P2): Brief done-when criterion "Config uses top-level `petasos:` key" not mapped in spec done-when
D8 describes the intent but done-when and test plan don't close the loop.

### F-3 (P3): Aggregate severity computation has no consumer in fail-mode
Stage 5 says "used internally for fail-mode" but §4.4 iterates individual findings. Orphaned prose.

### F-4 (P3): Plane ticket not cached in MCP memory
memory_search returned zero results for PET-6. Review used brief as canonical.

## Summary

P0: 0 | P1: 0 | P2: 2 | P3: 2

STATUS: GREEN
