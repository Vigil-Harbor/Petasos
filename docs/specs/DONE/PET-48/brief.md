# PET-48 · [RT PIPE-01] Cancel inspect() mid-gather

**Parent:** PET-14 (Red-team security review)
**Blocks:** PET-12 (Release)
**Priority:** Medium · **OWASP:** ASI07 (Guardrail bypass)
**Finding status:** refuted (vulnerability confirmed by cross-model review)

---

## Problem

`Pipeline.inspect()` and the helper `_scan_one()` use `except Exception` as
their top-level safety net. In Python 3.9+, `asyncio.CancelledError` is a
`BaseException`, not an `Exception`. Two consequences:

1. **`_scan_one` (L127–148):** If a task-level cancellation arrives while
   `asyncio.wait_for` is running, `CancelledError` escapes the `except
   Exception` block and propagates through `asyncio.gather` (L381), which
   has no `return_exceptions=True`. The gather itself then raises, and the
   exception reaches `inspect()`.

2. **`inspect` (L311–325):** The outer try/except catches `Exception`, so
   `CancelledError` escapes `inspect()` entirely — violating the
   **pipeline-never-throws invariant**.

An attacker (or a noisy runtime environment) that cancels the task running
`inspect()` mid-gather causes the pipeline to raise instead of returning a
safe `PipelineResult(safe=False, ...)`. Callers that don't expect an
exception from `inspect()` may fail open.

### Grounding

| Location | Current code | Issue |
|---|---|---|
| `_scan_one` L141 | `except Exception as exc:` | Misses `CancelledError` |
| `_inspect_inner` L381 | `asyncio.gather(*tasks)` | No `return_exceptions` — one `CancelledError` aborts all |
| `inspect` L325 | `except Exception as exc:` | Top-level guard misses `CancelledError` |

---

## Decisions Carried Forward

- **D1: `except BaseException` at the `inspect()` boundary, not `asyncio.shield`.** Shielding the entire `inspect()` call would prevent the caller from cancelling a long-running scan, which is a legitimate use case (e.g., Hermes timeout). The contract is "never throws" — not "never cancellable." We catch `BaseException` at the outermost `inspect()` level and return a well-formed `PipelineResult`. Callers who need cancellation semantics can wrap `inspect()` in their own shield.

- **D2: `_scan_one` catches `BaseException` (not just `Exception`).** Per-scanner isolation must cover cancellation: a cancelled scanner returns an errored `ScanResult`, and the remaining scanners in the gather continue. This is consistent with the existing error-isolation design.

- **D3: `asyncio.gather` gains `return_exceptions=True`.** Belt-and-suspenders with D2. If a scanner somehow raises a `BaseException` subclass we haven't anticipated, the gather still completes and returns the exception object. The merge stage treats exception objects as errored results.

- **D4: `_inspect_inner` exception types unchanged.** The inner method's various `except Exception` blocks (stages 5c, 6, 7, etc.) don't need `BaseException` because cancellation is already neutralized at D2/D3 before those stages run. The outer `inspect()` (D1) is the final backstop.

- **D5: `CancelledError` is logged, not silently swallowed.** When `BaseException` is caught at L325, log a warning with the exception type so cancellation events are observable (audit trail for Hermes integration debugging).

---

## Remediation

### `_scan_one` (L127–148)

Change `except Exception` to `except BaseException`. This ensures
`CancelledError`, `KeyboardInterrupt`, and `SystemExit` from a scanner
are caught and returned as an errored `ScanResult`.

### `asyncio.gather` call (L381)

Add `return_exceptions=True`. Post-gather, iterate results and convert
any `BaseException` instances to errored `ScanResult` objects before
passing to merge.

### `inspect` outer handler (L311–325)

Change `except Exception` to `except BaseException`. Add a
`_logger.warning(...)` call for non-`Exception` types. Return
`PipelineResult(safe=False, ...)` as today.

### Result conversion helper

Add a small helper to normalize gather output:

```python
def _normalize_gather_result(
    result: ScanResult | BaseException,
    scanner_name: str,
) -> ScanResult:
    if isinstance(result, BaseException):
        return ScanResult(
            scanner_name=scanner_name,
            findings=(),
            duration_ms=0.0,
            error=f"{type(result).__name__}: {result}",
        )
    return result
```

---

## Test Plan

Each fix requires tests that prevent the bug from recurring.

### Unit tests (`tests/adversarial/pipeline/test_cancel_mid_gather.py`)

1. **`test_inspect_catches_cancelled_error`** — Create a scanner whose
   `scan()` raises `asyncio.CancelledError`. Call `inspect()`. Assert it
   returns a `PipelineResult` (not raises), `safe=False`, error string
   mentions "CancelledError".

2. **`test_scan_one_isolates_cancelled_scanner`** — Call `_scan_one` with
   a scanner that raises `CancelledError`. Assert it returns an errored
   `ScanResult` (not raises).

3. **`test_gather_return_exceptions_isolates_failure`** — Configure two
   scanners: one raises `CancelledError`, the other returns normally.
   Call `inspect()`. Assert the healthy scanner's findings are present in
   the merged result and the cancelled scanner's error is recorded.

4. **`test_keyboard_interrupt_caught_at_boundary`** — Scanner raises
   `KeyboardInterrupt`. Assert `inspect()` returns `PipelineResult`,
   not raises.

5. **`test_cancelled_error_logged`** — Patch `_logger.warning`, trigger
   `CancelledError` through a scanner, assert the warning was emitted
   with the exception type.

### Regression integration test

6. **`test_mid_gather_cancel_full_pipeline`** — Full pipeline with
   premium features enabled. Cancel the `inspect()` task from outside
   after a short delay (simulating Hermes timeout). Assert the task's
   result is a `PipelineResult` (caught at boundary), not a raised
   `CancelledError`.

---

## Done When

- [ ] `_scan_one` catches `BaseException`, not `Exception`
- [ ] `asyncio.gather` uses `return_exceptions=True` with result normalization
- [ ] `inspect()` outer handler catches `BaseException`, not `Exception`
- [ ] `CancelledError` at the `inspect()` boundary is logged as a warning
- [ ] All 6 tests above pass
- [ ] `mypy --strict` clean, `ruff` clean
- [ ] Existing test suite passes (no regressions)
- [ ] `pytest --cov` shows the new `BaseException` branches are covered

## Out of Scope

- **Shielding individual scanners from cancellation.** Scanners should be cancellable; the fix is about *catching* the cancellation, not preventing it.
- **`TaskGroup` migration.** Python 3.11 `TaskGroup` has better cancellation semantics but would be a larger refactor across the gather pattern. Can be evaluated separately.
- **Other `except Exception` sites in `_inspect_inner`.** Per D4, these are downstream of the gather and already protected by D2/D3. If a future finding targets them, that's a separate ticket.
