# PET-59 Conventions Review — Round 1

## Closure of round 0 findings
N/A — round 1

## Findings

### F-1: Unit test file placed in nonexistent `tests/unit/premium/` directory — violates flat test layout
**Severity:** P1
Repo convention is flat tests under `tests/`. This was flagged and corrected in PET-31, PET-36, PET-22, PET-25 specs. Introducing `tests/unit/premium/` breaks the established pattern.
**Suggested fix:** Place tests in `tests/test_profiles_suppress.py`.

### F-2: `__post_init__` silently strips without logging, inconsistent with `_validate_suppress_rules()`
**Severity:** P2
Decision 1 says "strip and warn." `__post_init__` strips but does not warn.

### F-3: Spec and brief disagree on test file name (`test_profiles_suppress.py` vs `test_profiles.py`)
**Severity:** P3
Brief uses `test_profiles.py`, spec renames to `test_profiles_suppress.py`. Not acknowledged as a deviation.

### F-4: Module-level logger positioning
**Severity:** P4
Should follow existing premium module pattern: `import logging` in stdlib group, `_logger` after all imports.

### F-5: `register()` path covered transitively via `__post_init__` — not explicitly documented
**Severity:** P3
Add one-line note that `register()` is covered because `ResolvedProfile.__post_init__` fires at construction.

### F-6: Spec unsuppressible rule count — verified correct (13)
**Severity:** P4

### F-7: Decision 6 (module-level logger) — correctly documented as spec-level addition
**Severity:** P3

### F-8: Decision 3 (research.json `inst-delimiter` removal) — correctly documented
**Severity:** P3

### F-9: Spec test command references nonexistent path
**Severity:** P1
`python -m pytest tests/unit/premium/test_profiles_suppress.py ...` will fail since the directory doesn't exist.
**Suggested fix:** Fix per F-1.

## Summary
P0: 0 | P1: 2 | P2: 1 | P3: 3 | P4: 2

STATUS: RED P0=0 P1=2 P2=1 P3=3 P4=2
