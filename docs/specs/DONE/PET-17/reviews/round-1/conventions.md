# Conventions Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: Spec promotes memory bound to config field; brief specifies hardcoded constant
**Severity:** P3
**Where:** spec.md:61
**Note:** Reasonable promotion for consistency with `max_sessions` and `alert_ring_buffer_capacity`. Add rationale note to D3.

### F-2: Test command uses MSYS path instead of repo convention
**Severity:** P2
**Where:** spec.md:191
**Note:** `/c/python310/python` won't work in native Windows shell. PET-16 uses `.venv\Scripts\python.exe`.
**Suggested fix:** Use `python -m pytest tests/test_alerting.py tests/test_config.py -v` or pin to `.venv`.

### F-3: Config field placement not specified
**Severity:** P4
**Where:** spec.md:55-62
**Suggested fix:** Specify: "in the Alerting thresholds group after `alert_ring_buffer_capacity`."

### F-4: Validation placement in `__post_init__` not specified
**Severity:** P4
**Where:** spec.md:67-88
**Suggested fix:** Add: "after the `alert_ring_buffer_capacity` validation block (around L242)."

### F-5: Spec contradicts brief on `test_100_rapid_triggers_bounded`
**Severity:** P2
**Where:** spec.md:155-159
**Note:** Brief expected adjustment; spec says no change needed. Spec's analysis is correct but should acknowledge the discrepancy.

### F-6: Done-when adds "with validation" not in brief
**Severity:** P4
**Note:** Reasonable — pattern demands it.

### F-7: Config test naming granularity
**Severity:** P3
**Note:** PET-16 uses per-value tests; PET-17 proposes combined tests. Both defensible.

### F-8: Filemap count update
**Severity:** P4
**Note:** Handled by wiki skill post-merge.

### F-9: Test plan uses `per_minute_cap=10` matching brief's incorrect default
**Severity:** P3
**Note:** Explicit config override, not functionally wrong. Add clarifying note.

### F-10: "Pipeline never throws" invariant covered by existing error handling
**Severity:** P3
**Note:** Informational.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 4 | P4: 4

STATUS: GREEN
