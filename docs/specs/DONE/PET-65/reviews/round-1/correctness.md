# PET-65 Correctness Review -- Round 1

## Findings

### F-1: Spec narrows mypy --strict scope versus the brief (P2)
Spec uses `mypy --strict petasos/scanners/__init__.py` (single file) while brief requires `mypy --strict .` (project-wide). Silent deviation.

### F-2: Spec test set diverges from brief test set without acknowledgment (P3)
Brief has `test_transitive_dep_failure_reraises` and `test_missing_extra_swallows_silently`. Spec replaces with `test_is_missing_package_rejects_submodule` and renames to `test_missing_extra_removes_from_all`. Coverage is equivalent or better but undocumented.

### F-3: "Files to create" table labels all 8 tests as "unit tests" (P4)
Test plan separates them into 4 unit + 4 integration. Summary table should reflect this.

### F-4: Test command references Python 3.10 path while project requires >= 3.11 (P4)
`C:\python310\python.exe` path name suggests 3.10. Project requires 3.11+. May be misleading.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 1 | P4: 2

STATUS: GREEN
