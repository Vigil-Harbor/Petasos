# Conventions Review -- round 1

## Findings

### F-1: Test file naming breaks established convention
**Severity:** P3
**Where:** spec.md:25 (New files)
Existing test files use `test_<module>_<behavior>.py` not `test_<finding-id>_<description>.py`. Examples: `test_profiles_suppress.py` (PET-59), `test_safe_json.py` (PET-38), `test_frequency_tombstone.py` (PET-30). Recommend `tests/test_profiles_retained_ref.py`.

### F-2: Defensive-copy convention already established in config.py but not cross-referenced
**Severity:** P4
`petasos/config.py:193` already uses `MappingProxyType(dict(...))` for `frequency_weights`. The spec should cite this precedent.

### F-3: Spec adds `ruff format --check .` to "Done when" -- silent addition beyond brief
**Severity:** P3
Brief's Done When has 5 criteria; spec adds a 6th for ruff formatting. Good addition but not authorized by brief. Surfaced for drift-check.

### F-4: Test command scopes mypy to single file; CI runs whole-project
**Severity:** P4
Spec runs `mypy --strict petasos/premium/profiles/__init__.py`; CI runs `mypy --strict .`. Scoped approach is reasonable for iteration speed. Low stakes since CI catches regressions.

### F-5: Test import of private function follows established pattern
**Severity:** P4 (informational)
No change needed. Pattern established in `test_profiles.py:13`, `test_profiles_suppress.py:11`.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 2 | P4: 3

STATUS: GREEN
