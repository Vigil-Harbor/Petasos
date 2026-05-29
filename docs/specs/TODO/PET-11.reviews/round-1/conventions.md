# Conventions Review -- round 1

## Closure of round 0 findings
N/A -- round 1.

## Findings

### F-1: Spec proposes `MockMLScanner` duplicating existing `MockScanner` in `test_pipeline.py`
**Severity:** P2
**Where:** spec.md:142-157 (Mock Scanner Implementation)
**Suggested fix:** Reuse existing `MockScanner` or acknowledge duplication.

### F-2: Spec's `MockMLScanner.scan()` signature violates the Scanner protocol (missing type annotations)
**Severity:** P2
**Where:** spec.md:151-154
**Suggested fix:** Add type annotations matching the Scanner protocol.

### F-3: `asyncio.run()` inside benchmark callables conflicts with `asyncio_mode = "auto"`
**Severity:** P2
**Where:** spec.md:169, 195
**Suggested fix:** Replace `asyncio.run()` with `loop.run_until_complete()` or async test structure.

### F-4: `v1.0.0` tagging removed from done-when without explicit Decision
**Severity:** P2
**Where:** spec.md:280-301
**Suggested fix:** Add a Decision entry documenting the scope reduction.

### F-5: `license` module added to coverage targets — silent addition over brief
**Severity:** P3
Informational — rationale is adequate in Decision 7.

### F-6: Brief's platform footgun 4c scope reduction not fully acknowledged
**Severity:** P3
Informational — N/A rationale is solid in Decision 6.

### F-7: Test file count 20 should be 18
**Severity:** P3
**Suggested fix:** Correct to 18.

### F-8: `PipelineResult.status == "degraded"` referenced in brief but not in spec (correctly avoided)
**Severity:** P2
Informational — spec correctly references `safe == False`.

### F-9: `valid_key` fixture not in benchmark function signature
**Severity:** P2
**Suggested fix:** Add `valid_key` to the benchmark function signature.

## Summary
P0: 0 | P1: 0 | P2: 5 | P3: 3 | P4: 0

STATUS: GREEN
