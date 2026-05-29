# Conventions Review -- round 1

## Findings

### F-1: Wiki architecture.md and comprehension entry describe merge as "highest confidence wins"
**Severity:** P2
**Where:** spec.md whole document (missing from scope)
**Evidence:** `architecture.md` line 36 and `comprehension/2026-05-25-pet-6-pipeline-orchestrator.md` line 18 both describe pre-fix behavior. After PET-51 ships, both are factually wrong.
**Suggested fix:** Add wiki update note to "Done when" section.

### F-2: Spec line number reference for confidence floor filtering is off by ~10 lines
**Severity:** P4

### F-3: `_SEVERITY_RANK` duplicated in `pipeline.py` and `alerting.py`
**Severity:** P3
**Suggested fix:** Note as follow-up. Deferred to avoid scope creep.

### F-4: Pseudocode vs concrete code use different dict access patterns
**Severity:** P4 (acknowledged in spec)

### F-5: Spec does not mention `tests/test_finding_merge.py` impact analysis
**Severity:** P3
**Suggested fix:** Add to "Files to leave alone" with note that existing tests are unaffected.

### F-6: "Equal severity, equal confidence keeps both" decision — appropriate carry-forward from brief
**Severity:** P3 (no change needed)

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 3 | P4: 2

STATUS: GREEN
