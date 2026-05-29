# Conventions Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: CLAUDE.md fail-mode invariant description will become stale after PET-49
**Severity:** P2
**Where:** CLAUDE.md:102
**Suggested fix:** Add CLAUDE.md to the spec's change list.

### F-2: Spec claims "no-comment convention per CLAUDE.md" but no such convention exists
**Severity:** P2
**Where:** spec.md:25, spec.md:118
**Suggested fix:** Remove the false claim and provide accurate rationale.

### F-3: Brief requires `fail_mode` docstring update in config.py; spec explicitly opts out
**Severity:** P1
**Where:** spec.md:25
**Suggested fix:** Reinstate the `fail_mode` docstring update as a deliverable.

### F-4: Test name discrepancy with brief
**Severity:** P3
**Where:** spec.md:89
**Suggested fix:** Use brief's name `test_degraded_partial_ml_failure_with_findings_blocks`.

### F-5: Test command uses `python -m ruff` but CLAUDE.md uses bare `ruff`
**Severity:** P4

### F-6: Test command omits `ruff format --check .`
**Severity:** P3
**Suggested fix:** Add `&& ruff format --check .` to the test command.

### F-7: `mypy --strict` scoped to `petasos/` rather than `.`
**Severity:** P4
**Suggested fix:** Change to `python -m mypy --strict .`.

### F-8: RT-075 pre_fix_baseline analysis is a reasonable silent addition
**Severity:** P3 (acceptable)

### F-9: D1-D4 mapping to brief is clean
**Severity:** P4 (no change needed)

## Summary
P0: 0 | P1: 1 | P2: 2 | P3: 3 | P4: 3

STATUS: RED P0=0 P1=1 P2=2 P3=3 P4=3
