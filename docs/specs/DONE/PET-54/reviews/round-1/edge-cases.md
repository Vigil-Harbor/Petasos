# Edge-Cases Review -- round 1

## Findings

### F-1: Invalid severity string in override causes unhandled `ValueError` from `Severity()` (P1)
`severity_overrides` dict values may contain invalid Severity enum strings. `Severity(override)` raises `ValueError`, which propagates through `inspect()`'s catch-all and returns `PipelineResult(safe=False, findings=())` — erasing all findings. A DoS vector worse than the original downgrade attack.

### F-2: Empty `severity_overrides` dict truthiness check (P4)
Correctly evaluates to False for empty MappingProxyType. No issue.

### F-3: Concurrent `inspect()` calls — no race (P4)
All state is local. No shared mutable state touched. No issue.

### F-4: No test for the brief's specific attack scenario (P2)
No end-to-end test with actual injection rule and text that triggers it.

### F-5: Construction-time severity value validation missing (P2)
`_check_structural_overrides` only checks keys, not values. Invalid values pass construction and crash at runtime.

### F-6: `_STRUCTURAL_RULE_PREFIX` duplicated in two files — drift risk (P3)
Two identical constants in pipeline.py and profiles/__init__.py could diverge.

### F-7: `_STRUCTURAL_RULE_PREFIX` vs `_STRUCTURAL_RULE_IDS` — naming convention change risk (P3)
Prefix approach could miss new structural rules with different naming.

### F-8: Line number references will shift after edits (P2)
Spec references pre-edit line numbers. Implementer should use stage names and function names.

### F-9: Test file location mismatch between spec and brief — spec is correct (P2)
Brief's `tests/unit/premium/test_profiles.py` doesn't exist.

### F-10: Dropped brief's 9th test without explanation (P1)
Done-When says "All 8 tests" but brief requires 9. Dict-profile end-to-end path untested.

### F-11: `ValueError` from `_check_structural_overrides` and "pipeline never throws" (P2)
ValueError caught by `inspect()`'s catch-all, returns PipelineResult(safe=False, findings=()). Consistent with invariant but caller loses all findings.

### F-12: Same-severity override boundary (P4)
Correctly handled by `override_rank > current_rank` check. Test 4 covers this.

### F-13: "Test license fixture pattern from existing tests" — no such fixture exists (P2)
Spec should provide the license activation approach (monkeypatch).

### F-14: `ProfileResolver.register()` bypass (P2)
`register()` accepts any `ResolvedProfile` without validation. Runtime layer catches it.

## Summary
P0: 0 | P1: 2 | P2: 6 | P3: 2 | P4: 2

STATUS: RED P0=0 P1=2 P2=6 P3=2 P4=2
