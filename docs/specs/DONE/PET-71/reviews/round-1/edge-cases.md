# Edge-Cases Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: `test_suppress_encoding_rules_allowed` does not specify concrete test input or baseline
**Severity:** P2
Risk of vacuous pass — input may not trigger encoding findings, making "no encoding findings" assertion trivially true.
**Suggested fix:** Add concrete test body with baseline assertion.

### F-2: `test_suppress_mixed_set_filters_correctly` — same vacuous-pass risk, two conditions
**Severity:** P2
Must verify both injection-present AND encoding-absent with known-triggering input.
**Suggested fix:** Add concrete test body with baseline.

### F-3: New tests need `_ENCODING_RULE_IDS` and `_ALL_INJECTION_IDS` imports not specified
**Severity:** P2
Current imports in `test_injection_evasion.py` lack these names.
**Suggested fix:** Specify import additions in the spec.

### F-4: Double-stripping idempotency not documented
**Severity:** P3
`with_suppress_rules()` → `__init__` strips again on already-clean set. Harmless but undocumented.

### F-5: `try/except ValueError: return` dead code in `test_rt075_chain_syn08_breaks_link2`
**Severity:** P2
After silent-strip fix, `ValueError` never raised. Dead exception handler should be removed.
**Suggested fix:** Specify removal of try/except block alongside xfail removal.

### F-6: Brief/spec test count mismatch not reconciled
**Severity:** P3
Brief says "All 8 tests"; spec accounts for 5 + 3 already-existing. Mapping present but scattered.

### F-7: Brief Done-When "Profile parse/merge logs warning" — existing coverage not explicitly stated
**Severity:** P3
D6 explains it but Done-When lacks explicit acknowledgment.

### F-8: Unused imports in profiles after constant relocation (same as correctness F-1)
**Severity:** P2
Merged with correctness F-1.

### F-9: Pre-fix baseline xfail reason update may be misleading
**Severity:** P2
Test already fails after PET-49. Proposed reason "will fail after NORM-01 fix lands" omits the already-realized failure.

## Summary
P0: 0 | P1: 0 | P2: 5 | P3: 3 | P4: 0

STATUS: GREEN
