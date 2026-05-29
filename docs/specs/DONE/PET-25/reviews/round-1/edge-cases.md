# Edge-Cases Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: `test_all_bool_fields_covered` will fail at runtime due to `from __future__ import annotations`
**Severity:** P1
**Where:** spec.md:144 (test #8)
**Edge case:** `from __future__ import annotations` makes all annotations strings at runtime. The spec provides no implementation guidance for introspecting type annotations. A naive `f.type is bool` will match zero fields.
**Suggested fix:** Add implementation note specifying use of `typing.get_type_hints(PetasosConfig)`.

### F-2: `tests/unit/` directory does not exist
**Severity:** P2

### F-3: File existence clarity for adversarial test directory
**Severity:** P4

### F-4: Test plan count mismatch between spec and brief
**Severity:** P2

### F-5: No test for container types (list, dict) as bool field values
**Severity:** P3

### F-6: No explicit guidance on error message ordering for multiple invalid fields
**Severity:** P3

### F-7: Line number accuracy for __post_init__ insertion point
**Severity:** P4

### F-8: `_BOOL_FIELDS` underscore-prefix convention tension with test imports
**Severity:** P3

### F-9: __post_init__ bool check ordering with anonymize truthiness check
**Severity:** P4

## Summary
P0: 0 | P1: 1 | P2: 2 | P3: 3 | P4: 3

STATUS: RED P0=0 P1=1 P2=2 P3=3 P4=3
