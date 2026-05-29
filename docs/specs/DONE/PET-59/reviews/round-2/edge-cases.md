# PET-59 Edge-Cases Review — Round 2

## Closure of round 1 findings
All round-1 findings confirmed CLOSED. `__post_init__` delegates to `_validate_suppress_rules()`, test paths corrected, adversarial test specifies premium activation and dual assertion, deferred items documented.

## Findings

### F-1: Adversarial test underspecifies how custom profile reaches the pipeline
**Severity:** P2
Test should pass the suppress-all dict as a per-call profile override (`pipe.inspect(text, profile={"suppress_rules": list(RULE_TAXONOMY)})`) to exercise the `resolve() -> _merge_with_base() -> __post_init__` chain — the realistic attacker path.

### F-2: `__init__.py` inconsistent with majority adversarial subdirectories
**Severity:** P4

### F-3: `_merge_with_base` validates full union but spec doesn't document this as intentional
**Severity:** P3
Add comment: validates base + overrides, so base-profile poisoning via `register()` is also caught.

### F-4: No test for the warning log output
**Severity:** P3
Decision 1 "strip and warn" — the "warn" half is untested. Consider `caplog` assertion.

### F-5: `with_suppress_rules()` direct callers bypass profile layer
**Severity:** P3
Pre-existing; deferred to PET-71. Spec Decision 4 accurately scopes this.

### F-6: `register()` allows overwriting base profile — protected by both `__post_init__` and `_merge_with_base`
**Severity:** P3

### F-7: Empty frozenset micro-optimization unnecessary
**Severity:** P4

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 4 | P4: 2

STATUS: GREEN
