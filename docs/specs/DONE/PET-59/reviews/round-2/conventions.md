# PET-59 Conventions Review — Round 2

## Closure of round 1 findings
All round-1 findings confirmed CLOSED. Test paths corrected to flat layout, `__post_init__` delegates to `_validate_suppress_rules()`, brief/spec divergence documented in Deferred, `register()` coverage documented.

## Findings

### F-1: Test command `mypy --strict` scoped to single file, contradicts Done-when
**Severity:** P2
PET-49 flagged this exact pattern. Recent specs (PET-31, PET-36, PET-30) all use `mypy --strict .`.
**Suggested fix:** Change to `mypy --strict .`.

### F-2: `tests/adversarial/profiles/__init__.py` deviates from majority convention
**Severity:** P4
Only `frequency/` has `__init__.py` among 7 adversarial subdirectories.

### F-3: Design section 1 import grouping cosmetic
**Severity:** P3
ruff auto-reorders imports. Show intended final state.

### F-4: Decision 3 research.json removal is a category (c) spec addition
**Severity:** P3
Sound rationale. Flagged for human drift-check.

### F-5: Test command omits `ruff format --check .`
**Severity:** P3
PET-31, PET-36, PET-30 all include it.

### F-6: Decision 6 module-level logger supersedes brief pattern
**Severity:** P3
Category (c) spec addition, correctly documented.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 4 | P4: 1

STATUS: GREEN
