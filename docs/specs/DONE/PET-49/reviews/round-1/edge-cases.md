# Edge-Cases Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: Spec cites nonexistent "no-comment convention per CLAUDE.md" to justify dropping brief's docstring requirement
**Severity:** P1
**Where:** spec.md:25
**Suggested fix:** Either reinstate the docstring update or provide truthful rationale.

### F-2: Test #3 requires a mock scanner not declared in the spec
**Severity:** P1
**Where:** spec.md:83, spec.md:89
**Suggested fix:** Add `_HighFindingScanner` mock definition to the spec's test plan.

### F-3: CLAUDE.md "Key Design Invariants" contradicts the fix
**Severity:** P2
**Where:** CLAUDE.md:102
**Evidence:** CLAUDE.md states: "partial scanner failure passes content" -- after PET-49 this is wrong.
**Suggested fix:** Add CLAUDE.md to the spec's change list.

### F-4: No test for single-ML-scanner error case
**Severity:** P2
**Where:** spec.md:85-91
**Suggested fix:** Consider adding a test with 1x `_ErrorScanner` in degraded mode.

### F-5: Should note semantic shift in pre_fix_baseline test
**Severity:** P3
**Where:** spec.md:71
**Suggested fix:** Add a sentence about the test's semantic role shift.

### Non-findings (verified safe)
- F-6: `_compute_safe` is a pure function — thread-safe.
- F-7: Early-exit in closed mode bypasses `_compute_safe` — correct.
- F-8: All-ML-succeed-with-HIGH-findings returns `safe=False` from findings — correct.

## Summary
P0: 0 | P1: 2 | P2: 2 | P3: 1 | P4: 0

STATUS: RED P0=0 P1=2 P2=2 P3=1 P4=0
