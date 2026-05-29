# Correctness Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: Spec's proposed `profiles/__init__.py` import line leaves `_ALL_INJECTION_IDS` and `_STRUCTURAL_RULE_IDS` as unused imports, failing ruff F401
**Severity:** P1
After removing the local `_UNSUPPRESSIBLE_RULE_IDS` definition at L15, both `_ALL_INJECTION_IDS` and `_STRUCTURAL_RULE_IDS` become unused imports. Ruff F401 would flag them. The spec's proposed import line keeps all three names but only `_UNSUPPRESSIBLE_RULE_IDS` is used in the file body (at L19 and L25 in `_validate_suppress_rules`).
**Suggested fix:** Import only `_UNSUPPRESSIBLE_RULE_IDS` from `minimal.py`. Drop `_ALL_INJECTION_IDS` and `_STRUCTURAL_RULE_IDS`.

### F-2: Brief test `test_profile_suppress_injection_logged` requires asserting warning log emission, existing test only checks stripping
**Severity:** P2
The brief's test explicitly requires asserting a warning log is emitted. The existing `test_parse_profile_strips_injection_rules` checks stripping behavior but not log emission. The logging is implemented; test coverage is the gap.
**Suggested fix:** Note the coverage gap in the Tests NOT added mapping table.

### F-3: Before/After code blocks for `profiles/__init__.py` combine non-contiguous lines
**Severity:** P2
The "Before" block shows L11 and L15 as consecutive, but L13 (`_logger`) sits between them.
**Suggested fix:** Add line-number annotations.

## Summary
P0: 0 | P1: 1 | P2: 2 | P3: 0 | P4: 0

STATUS: RED P0=0 P1=1 P2=2 P3=0 P4=0
