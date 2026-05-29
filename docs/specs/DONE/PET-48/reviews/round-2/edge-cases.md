# Edge-Cases Review -- round 2

## Closure of round 1 findings

All P1 findings CLOSED: D7 addresses KI/SE (F-1), D2 rewritten for external cancellation (F-2). P2 findings CLOSED: test 6 event-based (F-3), error format handles empty strings (F-4), D4 acknowledges post-gather cancellation (F-5), wait_for documented in OOS (F-8). P3 findings F-7/F-9/F-10 acknowledged as acceptable gaps.

## Findings

### F-1: `inspect()` boundary errors tuple empty string for CancelledError
**Severity:** P2
Same issue as correctness R2 F-1. The `PipelineResult.errors` field carries `""` for bare CancelledError while `_scan_one` and `_normalize_gather_result` produce type-name strings.

### F-2: Test 3 assertion target unclear
**Severity:** P2
Test 3 says "cancelled scanner's error recorded" without specifying where — `PipelineResult.errors` vs `PipelineResult.scanner_results[i].error`.

### F-3: `_normalize_gather_result` duration_ms always 0.0
**Severity:** P3
Minor fidelity loss in the fallback path.

### F-4: mypy treatment of `gather(return_exceptions=True)` not discussed
**Severity:** P2
May need a `cast` or `# type: ignore` for strict mypy.

### F-5: Test 6 event.wait() should have a timeout
**Severity:** P3
Prevents deadlock if pipeline fails before reaching gather.

### F-6: No test for SystemExit or GeneratorExit
**Severity:** P3
CancelledError and KeyboardInterrupt covered; SystemExit is the remaining untested BaseException subclass.

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 3 | P4: 0

STATUS: GREEN
