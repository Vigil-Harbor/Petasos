# Correctness Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: `tests/unit/` directory does not exist; breaks convention
**Severity:** P2
**Where:** spec.md:21, spec.md:128
**Claim:** "tests/unit/test_config.py | New file -- unit tests for bool coercion (7 tests)"
**Why this is wrong:** The repository has no `tests/unit/` directory. All existing unit-level tests live flat under `tests/`. Creating `tests/unit/` introduces a new organizational convention that splits config tests across two locations.
**Suggested fix:** Place new unit tests in the existing `tests/test_config.py` as new test classes, or use `tests/test_config_bool_coercion.py`.

### F-2: Test command uses Git Bash path syntax, not portable
**Severity:** P2
**Where:** spec.md:166
**Suggested fix:** Use `python -m pytest <paths> -v` or just `pytest <paths> -v`.

### F-3: "Files to leave alone" section lists a file that must be changed
**Severity:** P2
**Where:** spec.md:23-29
**Suggested fix:** Move `tests/adversarial/config/test_config_poisoning.py` from "Files to leave alone" to "Files to change".

### F-4: Brief says 9 tests, spec says 11 -- expansion not explicitly reconciled
**Severity:** P3

### F-5: `from __future__ import annotations` complicates `test_all_bool_fields_covered` introspection
**Severity:** P3
**Suggested fix:** Add implementation note to use `typing.get_type_hints(PetasosConfig)`.

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 2

STATUS: GREEN
