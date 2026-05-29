# Correctness Review -- round 2

## Closure table
All round 1 findings CLOSED:
- correctness F-1 (SYN-* divergence): CLOSED — Decision 3 now explicitly notes the divergence
- correctness F-2 (missing 9th test): CLOSED — test 7 added as `test_dict_profile_override_critical_blocked`
- correctness F-3 (`_merge_with_overrides` name): CLOSED — spec uses correct `_merge_with_base`
- correctness F-4 (test 8 readability): CLOSED — test 10 now uses "info"
- correctness F-5 (`_STRUCTURAL_RULE_IDS` exists): CLOSED — no issue
- correctness F-6 (test file location): CLOSED — spec uses correct path
- correctness F-7 (brief line numbers stale): CLOSED — no issue
- edge-cases F-1 through F-14: all CLOSED per evidence in review
- conventions F-1 through F-7: all CLOSED per evidence in review

## Findings

### F-1: Cross-reference error: prose cites "test 9" but should cite "test 10" (P2)
Spec line 151 describes the dict-profile structural override path through `resolve()` → `_merge_with_base()`. Test 10 covers this, not test 9.

### F-2: No end-to-end test for dict profile with structural rule override through `inspect()` (P3)
Test 10 validates `resolve()` raises ValueError directly. The full `inspect()` path (dict → resolve → ValueError → catch-all → PipelineResult) is covered by composition.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 1 | P4: 0

STATUS: GREEN
