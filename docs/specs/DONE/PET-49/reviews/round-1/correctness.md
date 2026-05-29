# Correctness Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: Brief acceptance criterion #2 (fail_mode docstring update) rejected on fabricated grounds
**Severity:** P1
**Where:** spec.md:25, spec.md:118
**Claim:** "config.py -- fail_mode field has no docstring today (frozen dataclass field with type annotation only); adding a comment would violate the project's no-comment convention per CLAUDE.md."
**Why this is wrong:** CLAUDE.md has no "no-comment convention." The brief explicitly lists "`fail_mode` docstring updated in `config.py`" as Done-When criterion #2 (brief line 88). The spec fabricates a nonexistent CLAUDE.md convention to justify skipping a brief acceptance criterion.
**Suggested fix:** Remove the "Out of scope" and "Files unchanged" entries that reject this criterion. Add `config.py` to the "Files changed" table with a task to add a comment to the `fail_mode` field describing the three modes.

### F-2: Test #3 requires a mock scanner not present in the file
**Severity:** P1
**Where:** spec.md:83, spec.md:89
**Claim:** "All tests use `_ErrorScanner` and `_CleanScanner` mock scanners already defined in the file."
**Why this is wrong:** Test #3 (`test_degraded_partial_with_findings_blocks`) requires "1x scanner that returns HIGH finding." None of the existing mock scanners return findings. A new mock is needed.
**Suggested fix:** Add a `_HighFindingScanner` mock class to the test plan.

### F-3: Test count mismatch between brief and spec
**Severity:** P2
**Where:** spec.md:107
**Suggested fix:** Reword to: "6 adversarial tests pass (1 renamed + 5 new)."

### F-4: Test command uses `mypy --strict petasos/` but Done-When says `mypy --strict .`
**Severity:** P2
**Where:** spec.md:100-101 vs spec.md:109
**Suggested fix:** Change to `python -m mypy --strict .`.

### F-5: Test #3 name differs from brief
**Severity:** P4
**Where:** spec.md:89
**Suggested fix:** Use the brief's name: `test_degraded_partial_ml_failure_with_findings_blocks`.

## Summary
P0: 0 | P1: 2 | P2: 2 | P3: 0 | P4: 1

STATUS: RED P0=0 P1=2 P2=2 P3=0 P4=1
