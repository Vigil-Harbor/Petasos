# Correctness Review — PET-67 Round 1

## Findings

### F-1: Spec omits `@pytest.mark.asyncio` decorator from adversarial test "after" code block
**Severity:** P2
**Where:** spec.md:67-74 (section "Adversarial test flip")
The spec's "after" code block omits the `@pytest.mark.asyncio` decorator present at L21 of the existing file. While `asyncio_mode = "auto"` makes this functional, a literal paste could drop the decorator, breaking the file's internal consistency.
**Suggested fix:** Add `@pytest.mark.asyncio` to the "after" code block or note to preserve the existing decorator.

### F-2: Brief says extend `test_system_prefix`; spec creates separate test
**Severity:** P4
The brief says "Unit test `test_system_prefix` covers at least one lowercase variant" (extending existing). The spec creates a new `test_system_prefix_case_insensitive` method — arguably cleaner. Done-when is satisfied either way.

### F-3: No new imports needed — cosmetic observation
**Severity:** P3
The adversarial test "after" code uses builtins only; no import changes needed. Cosmetic.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 1 | P4: 1

STATUS: GREEN
