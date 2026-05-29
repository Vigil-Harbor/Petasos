# Conventions Review — PET-16 Round 1

## Findings

### F-1: Spec line references "L95-121" slightly off (P4)
**Where:** spec.md:93
**Issue:** Actual range is L95-120; L121 is blank. Cosmetic.

### F-2: _prune_stale line reference tilde unnecessary (P4)
**Where:** spec.md:144
**Issue:** "~L337-343" is exact. Tilde is harmless.

### F-3: Config validation tests misaligned with existing repo pattern (P3)
**Where:** spec.md:199-205
**Issue:** No existing alert cap fields have dedicated config validation tests in test_config.py. Adding them only for the new field creates inconsistency.

### F-4: Test command uses .venv path inconsistent with sibling specs (P2)
**Where:** spec.md:209
**Issue:** `.venv\Scripts\python.exe` is a new variant. PET-17 uses `/c/python310/python`. Prior specs use various paths.
**Suggested fix:** Align with recent sibling spec convention.

### F-5: Decision 5 is spec-level addition (P3)
**Where:** spec.md:50-52
**Issue:** Brief's out-of-scope note promoted to formal decision. Correctly handled — makes boundary explicit.

### F-6: Test 3 narrative is overly long and self-contradictory (P2)
**Where:** spec.md:171
**Issue:** 12-line stream-of-consciousness. Test plan body (L187-188) is clean.
**Suggested fix:** Trim to match Test plan description.

### F-7: Test 5 is a useful new test, not a meta-test (P3)
**Where:** spec.md:168, 175-176
**Issue:** Framing says "meta-test" but test plan body defines a new concrete test.
**Suggested fix:** Remove "meta-test" label; describe the actual test.

### F-8: Missing --tb=short flag (P4)
**Where:** spec.md:209
**Issue:** Some prior specs include it, others don't. No strong convention.

### F-9: Frozen dataclass invariant preserved (P3 — positive confirmation)
**Where:** spec.md:56-78
**Issue:** None — correctly handled. `fields()` iteration auto-includes new field.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 4 | P4: 3

STATUS: GREEN
