# Correctness Review -- round 1

## Findings

### F-1: Brief specifies `SYN-*` prefix; spec narrows to `petasos.syntactic.structural.*` -- justified divergence (P2)
The brief's `SYN-*` prefix does not match any actual rule ID. The spec correctly adapts to the real prefix. Decision 3 explains the rationale.

### F-2: Brief requires 9 tests; spec provides 8 -- dropped `test_dict_profile_override_critical_blocked` (P1)
No end-to-end test covers the dict-profile path (`inspect(profile={"severity_overrides": {...}})`) where the override goes through `ProfileResolver.resolve()` → `_merge_with_base()` → pipeline runtime severity floor. This is the exact attack scenario from the brief's Problem section.

### F-3: Brief uses `_merge_with_overrides`; actual function is `_merge_with_base` (P4)
Spec correctly uses `_merge_with_base`. Brief's name was a paraphrase.

### F-4: Test 8 uses "critical" for structural rule override -- readability (P3)
Using "info" instead of "critical" would make the test intent clearer.

### F-5: `_STRUCTURAL_RULE_IDS` exists at minimal.py L77; spec correctly notes no changes needed (P4)

### F-6: Test file location differs from brief -- spec uses correct path (P2)
Brief references nonexistent `tests/unit/premium/test_profiles.py`. Spec uses actual `tests/test_profiles.py`.

### F-7: Brief line numbers stale; spec line numbers correct (P4)

## Summary
P0: 0 | P1: 1 | P2: 2 | P3: 1 | P4: 3

STATUS: RED P0=0 P1=1 P2=2 P3=1 P4=3
