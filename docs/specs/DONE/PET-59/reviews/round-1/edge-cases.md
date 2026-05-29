# PET-59 Edge-Cases Review — Round 1

## Closure of round 0 findings
N/A — round 1

## Findings

### F-1: `__post_init__` does not log a warning, breaking strip-and-warn invariant
**Severity:** P2
Direct `ResolvedProfile(...)` construction strips but does not warn. Decision 1 contract partially honored.
**Suggested fix:** Call `_validate_suppress_rules()` from `__post_init__`.

### F-2: `ProfileResolver.register()` accepts pre-built `ResolvedProfile` — `__post_init__` covers it
**Severity:** P3
`register()` stores directly, but `__post_init__` fires at construction time. Covered transitively.

### F-3: Double-stripping on `_merge_with_base` return path
**Severity:** P2
`_validate_suppress_rules` cleans the set, then `__post_init__` runs again on already-clean set. Harmless but should be documented as intentionally idempotent.

### F-4: Test directory `tests/unit/premium/` does not exist
**Severity:** P1
The spec places 7 unit tests in `tests/unit/premium/test_profiles_suppress.py`, but no `tests/unit/` directory exists. All unit tests live flat under `tests/`.
**Suggested fix:** Place tests in `tests/test_profiles_suppress.py`.

### F-5: Adversarial test directory `tests/adversarial/profiles/` does not exist
**Severity:** P2
Needs to be created. Follows existing adversarial convention (`tests/adversarial/guard/`, `tests/adversarial/frequency/`).

### F-6: Adversarial test does not specify premium license activation
**Severity:** P2
Without premium license, profile suppress_rules never reach the scanner. Test would pass trivially without PET-59 fix.
**Suggested fix:** Specify that the test must activate premium license and verify at both profile and pipeline layers.

### F-7: `_merge_with_base` validates full union (base + overrides) — correct but undocumented
**Severity:** P3
Catches base-profile leaks coincidentally. Add comment noting intentional full-union validation.

### F-8: Type correctness of `_validate_suppress_rules` argument — verified correct
**Severity:** P4

### F-9: 13 unsuppressible rule count — verified correct
**Severity:** P4

### F-10: Circular import risk between profiles and minimal scanner
**Severity:** P2
Today safe. Constrains future evolution — `scanners/minimal.py` must not import from `premium/profiles/`.

### F-11: Thread safety of `_logger.warning()` — not an issue
**Severity:** P4
Python logging is thread-safe by design.

### F-12: Existing tests construct `ResolvedProfile` with non-unsuppressible IDs — no impact
**Severity:** P2
Existing tests use `rule.a`, `rule.x` etc. Safe, but `__post_init__` makes it impossible to construct with unsuppressible IDs for any purpose.

## Summary
P0: 0 | P1: 1 | P2: 5 | P3: 2 | P4: 4

STATUS: RED P0=0 P1=1 P2=5 P3=2 P4=4
