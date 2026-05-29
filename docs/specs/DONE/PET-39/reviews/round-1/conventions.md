# Conventions Review -- round 1

## Findings

### F-1: mypy --strict scope in test command is narrower than CI
**Severity:** P2
**Where:** spec.md:195
CI runs `mypy --strict .` but spec scopes to touched files only. Established pattern in prior specs (PET-57, PET-65). Low impact.

### F-2: Test file name does not follow adversarial naming convention
**Severity:** P3
**Where:** spec.md:27, spec.md:160
Existing adversarial files use attack-centric names (`test_jwt_attacks.py`, `test_tool_smuggling.py`). Spec proposes `test_license_hardening.py` (fix-centric). Defensible as a batch name.

### F-3: Missing __init__.py addressed (informational)
**Severity:** P4
Consistent with majority pattern. Only `frequency/` has an anomalous `__init__.py`. No change needed.

### F-4: Decision 2 adds "standard" to tier allowlist
**Severity:** P3
Well-reasoned addition with explicit rationale. Brief deviation documented.

### F-5: Decision 5 adds negative clock skew check
**Severity:** P3
Reasonable defense-in-depth addition beyond brief scope. Rationale provided.

### F-6: Done-when count diverges from brief (8 → 13)
**Severity:** P2
All additions are additive (nothing dropped). Acceptable scope growth.

### F-7: __init__.py re-export impact not mentioned
**Severity:** P4
No new public exports introduced. Omission is deliberate.

### F-8: Test 5 ambiguous assertion
**Severity:** P2
Test accepts both VALID and INVALID — not a useful regression gate.

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 3 | P4: 2

STATUS: GREEN
