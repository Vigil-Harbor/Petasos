# Conventions Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: Test file placement in nonexistent `tests/unit/` breaks project convention
**Severity:** P1
**Where:** spec.md:21, spec.md:128
**Convention violated:** All existing unit tests live flat under `tests/` (e.g., `tests/test_config.py`). No `tests/unit/` directory exists.
**Suggested fix:** Add tests as new classes in existing `tests/test_config.py`.

### F-2: Spec and brief disagree on test count
**Severity:** P2
**Suggested fix:** Acknowledge expanded test list in spec.

### F-3: Adversarial test directory existence
**Severity:** P3

### F-4: Error message format introduces new pattern
**Severity:** P3
**Suggested fix:** Adopt existing pattern: `f"{fname} must be a bool, got {val!r}"`.

### F-5: Silent spec additions over brief
**Severity:** P3

### F-6: Existing adversarial test `test_from_dict_disables_normalization_via_falsy_zero` will break
**Severity:** P1
**Where:** spec.md:16-29
**Evidence:** `tests/adversarial/pipeline/test_degraded_fail_open.py` contains test that does `PetasosConfig.from_dict({"normalize_nfkc": 0})` and expects success. After fix, this raises TypeError. Spec does not list this file.
**Suggested fix:** Add to "Files to change" and update.

### F-7: `_BOOL_FIELDS` naming follows convention (positive)
**Severity:** P4

### F-8: Test import pattern consistent (positive)
**Severity:** P4

### F-9: Test command uses hardcoded path
**Severity:** P4

## Summary
P0: 0 | P1: 2 | P2: 1 | P3: 3 | P4: 3

STATUS: RED P0=0 P1=2 P2=1 P3=3 P4=3
