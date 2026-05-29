# PET-59 Correctness Review — Round 1

## Closure of round 0 findings
N/A — round 1

## Findings

### F-1: `__post_init__` does not log a warning, diverging from `_validate_suppress_rules` and Decision 1
**Severity:** P2
**Where:** spec Design section 5
The `__post_init__` code silently strips unsuppressible rules without logging. Decision 1 states "silently stripped with a `logging.warning()`." The `_validate_suppress_rules()` helper logs but `__post_init__` does not.
**Suggested fix:** Call `_validate_suppress_rules()` from `__post_init__` or add explicit logging.

### F-2: Brief references stale line numbers, but spec line numbers are accurate
**Severity:** P4
Brief cites `_merge_with_base()` at L93-99, spec corrected to L110. No spec change needed.

### F-3: `test_suppress_rules_union` in existing tests uses non-injection IDs — no change needed
**Severity:** P3
The existing test at `tests/test_profiles.py:196-203` uses `rule.a`, `rule.b` which won't be stripped. Passes as-is.

### F-4: `tests/unit/premium/` directory does not exist
**Severity:** P3
All current tests are flat in `tests/`. Only `tests/adversarial/` uses subdirectories.

### F-5: New test directory structure diverges from project convention
**Severity:** P2
Introducing `tests/unit/premium/` creates a new convention. Existing flat layout: `tests/test_profiles.py`, `tests/test_guard.py`, etc.
**Suggested fix:** Place tests in `tests/test_profiles_suppress.py` or add to existing `tests/test_profiles.py`.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 2 | P4: 1

STATUS: GREEN
