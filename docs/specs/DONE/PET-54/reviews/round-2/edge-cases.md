# Edge-Cases Review -- round 2

## Closure table
All round 1 P1 findings CLOSED:
- edge-cases F-1 (invalid severity string): CLOSED — Decision 6 + try/except in pipeline + _check_severity_values + test 8
- edge-cases F-10 (dropped 9th test): CLOSED — test 7 added
All round 1 P2-P4 findings CLOSED or N/A per evidence in review.

## Findings

### F-1: Same-severity override creates unnecessary object allocation (P3)
When override_rank == current_rank, `replace(f, severity=override_sev)` creates a new object identical to the original. Negligible perf concern; test 4 covers correctness.

### F-2: Case sensitivity of severity override values (P2)
`_check_severity_values` rejects "CRITICAL" (uppercase). At runtime, `Severity("CRITICAL")` also raises ValueError, caught by try/except. System is fail-safe. Error message could hint at correct format.

### F-3: Test 7 name "blocked" vs "floored" semantics (P2)
The override is silently floored, not blocked. Test name implies blocking.

### F-4: Test 9 requires "name" key in dict (P3)
`_parse_profile` accesses `data["name"]` — test dict must include it.

### F-5: Merge path inherits overrides from base profile (P3)
Check runs after `severity.update(val)`, catching both sources. No issue.

### F-6: No combined-violation test (P3)
Each guard tested in isolation; combined path not tested. Guards are independent per-finding.

### F-7: Error message omits attempted severity values (P3)
Minor debuggability concern.

### F-8: `_SEVERITY_RANK.get(f.severity, 999)` fallback for unknown severity (P2)
Cannot occur today (closed enum). Existing pattern from merge_findings.

### F-9: ResolvedProfile construction requires MappingProxyType (P4)
Implicit from dataclass definition. No spec change needed.

### F-10: Test 7 safe=False depends on injection rule being HIGH (P2)
True today and likely to remain. Test should assert `f.severity == Severity.HIGH` as precondition.

## Summary
P0: 0 | P1: 0 | P2: 4 | P3: 5 | P4: 1

STATUS: GREEN
