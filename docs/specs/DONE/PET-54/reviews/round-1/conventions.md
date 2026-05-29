# Conventions Review -- round 1

## Findings

### F-1: Duplicated `_STRUCTURAL_RULE_PREFIX` across two modules (P2)
PET-59 imports `_STRUCTURAL_RULE_IDS` from `minimal.py` in profiles/__init__.py. PET-54 should align with this pattern rather than duplicating a string constant.

### F-2: PET-54 and PET-59 modify same functions without cross-referencing (P2)
Both modify `_parse_profile` and `_merge_with_base`. Neither references the other.

### F-3: `ValueError` at profile construction vs "pipeline never throws" (P3)
Existing GUARD-03 (PET-36) also raises ValueError at construction. `inspect()`'s catch-all handles it.

### F-4: Test file placement differs from PET-59/PET-36 adversarial pattern (P3)
PET-54 puts profile tests in `tests/test_profiles.py` rather than `tests/adversarial/`. The general file already has profile validation tests, so this is acceptable.

### F-5: Decision 3 narrows brief scope without explicit divergence callout (P2)
The spec should explicitly note it diverges from the brief's `SYN-*` decision.

### F-6: Test 6 validates existing behavior, not PET-54 changes (P3)
Regression test for Decision 5 out-of-scope behavior. Acceptable as defense-in-depth.

### F-7: Two `_STRUCTURAL_RULE_PREFIX` constants with no sync tripwire (P3)
No test ensures the two copies stay aligned.

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 4 | P4: 0

STATUS: GREEN
