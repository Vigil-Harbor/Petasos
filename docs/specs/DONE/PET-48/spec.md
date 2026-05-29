# PET-48 Spec: Cancel inspect() mid-gather

**Ticket:** PET-48 (PIPE-01) · **Priority:** Medium · **OWASP:** ASI07
**Parent:** PET-14 · **Blocks:** PET-12 (release)
**Finding status:** refuted (vulnerability confirmed by cross-model review)

---

## Goal

Harden the pipeline's exception-handling boundary so that `CancelledError`, `KeyboardInterrupt`, and other `BaseException` subclasses cannot escape `inspect()`. Today, three `except Exception` blocks let these exceptions propagate — violating the **pipeline-never-throws invariant** and potentially causing callers to fail open.

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/pipeline.py` | (1) Add `import logging` + module-level `_logger`. (2) `_scan_one` L141: `except Exception` → `except BaseException`. (3) `asyncio.gather` L381: add `return_exceptions=True` + post-gather normalization. (4) `inspect` L325: `except Exception` → `except BaseException` + warning log for non-`Exception` types. |
| `tests/adversarial/pipeline/test_cancel_mid_gather.py` | New file — 6 tests per brief's test plan. |

### Files to leave alone

- `petasos/_types.py` — `ScanResult`, `PipelineResult`, `ScanFinding` unchanged
- `petasos/config.py` — no config surface changes
- `petasos/premium/` — premium hooks are downstream of gather; D4 says their `except Exception` blocks don't need `BaseException`
- `petasos/normalize.py` — upstream of gather
- `petasos/scanners/` — scanner backends unchanged
- `tests/adversarial/pipeline/test_degraded_fail_open.py` — existing tests unaffected (use `Exception` subclasses only)

## Decisions

### D1: `except BaseException` at the `inspect()` boundary, not `asyncio.shield`

Shielding `inspect()` would prevent legitimate caller cancellation (e.g., Hermes timeout). The contract is "never throws" — not "never cancellable." We catch `BaseException` at the outermost `inspect()` level and return a well-formed `PipelineResult(safe=False)`. Callers who need cancellation semantics wrap `inspect()` in their own shield.

### D2: `_scan_one` catches `BaseException`

Per-scanner isolation must cover cancellation: a cancelled scanner returns an errored `ScanResult`. When external cancellation arrives (e.g., `task.cancel()` on the `inspect()` task), all scanners in the gather receive `CancelledError` simultaneously — each converts it to an errored result, and the gather completes normally. This preserves the invariant that gather always returns a list of `ScanResult` objects. For scanner-internal exceptions (a buggy scanner raising `CancelledError` on its own), only that scanner is affected while others continue.

### D3: `asyncio.gather` gains `return_exceptions=True`

Belt-and-suspenders with D2. If a scanner somehow raises a `BaseException` subclass that slips past `_scan_one`, the gather still completes and returns the exception object. A post-gather normalization step converts exception objects to errored `ScanResult` instances before merge.

### D4: `_inspect_inner` exception types unchanged

The inner method's various `except Exception` blocks (stages 5c, 6, 7, etc.) don't need `BaseException` because scanner-originated cancellation is neutralized at D2/D3 before those stages run. For external cancellation arriving during post-gather stages (e.g., `task.cancel()` while executing stage 6's frequency hook), the `CancelledError` escapes the stage's `except Exception` and propagates to the outer `inspect()` handler (D1), which is the final backstop. Partial results computed in stages 1-5 are lost in this case — the returned `PipelineResult` has empty findings and only the cancellation error. This is acceptable: the caller cancelled the operation, so partial results are moot.

### D5: `CancelledError` is logged, not silently swallowed

When `BaseException` is caught at `inspect()` L325, log a warning with the exception type so cancellation events are observable for Hermes integration debugging. The log fires only for non-`Exception` types (the existing `except Exception` path already returns silently by design).

### D6: Logger follows module convention

`pipeline.py` currently has no logger. Add `import logging` and `_logger = logging.getLogger(__name__)` at module level. This is the standard Python pattern and matches the convention used in `petasos/premium/alerting.py`, `petasos/premium/guard.py`, and `petasos/premium/profiles/__init__.py`.

### D7: `KeyboardInterrupt` and `SystemExit` are caught, not re-raised

The brief's D1 and D2 specify `except BaseException`, which catches `KeyboardInterrupt` and `SystemExit` in addition to `CancelledError`. This is intentional: the pipeline-never-throws invariant means *never*, including process signals. A scanner that triggers `sys.exit()` or receives a signal should not crash the pipeline. The trade-off: `Ctrl+C` during a pipeline scan returns `PipelineResult(safe=False)` instead of interrupting the process. Callers (e.g., Hermes) that need `KeyboardInterrupt` propagation should wrap `inspect()` in their own signal handler. Test 4 explicitly validates this behavior.

## Design

### 1. Add logger to `pipeline.py`

Add `import logging` to the stdlib import block (between `import asyncio` on line 3 and `import os` on line 4). Place `_logger` after the last real import (`from petasos.scanners.minimal import MinimalScanner` on line 26) and before the `if TYPE_CHECKING:` block (line 28), consistent with the placement in `alerting.py`, `guard.py`, and `profiles/__init__.py`:

```python
_logger = logging.getLogger(__name__)
```

### 2. `_scan_one` exception broadening (L141)

**Before:**
```python
    except Exception as exc:
```

**After:**
```python
    except BaseException as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return ScanResult(
            scanner_name=sname,
            findings=(),
            duration_ms=elapsed,
            error=f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__,
        )
```

Two changes: (1) `except Exception` → `except BaseException`. (2) Error format changed from `error=str(exc)` to include the exception type name. When `str(exc)` is non-empty, the format is `"TypeName: message"`; when empty (as with bare `CancelledError()` in Python 3.11+), it falls back to just `"CancelledError"`. This unifies the format with `_normalize_gather_result`.

### 3. Gather normalization helper

Add a module-level helper after `_scan_one`:

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
            error=f"{type(result).__name__}: {result}" if str(result) else type(result).__name__,
        )
    return result
```

Type annotation uses `ScanResult | BaseException` because `asyncio.gather(return_exceptions=True)` returns a list of either the coroutine's return type or the raised exception.

### 4. `_inspect_inner` gather call (L377–381)

**Before:**
```python
        tasks = [
            _scan_one(s, normalized_text, direction=direction, session_id=session_id)
            for s in self._ml_scanners
        ]
        ml_results = list(await asyncio.gather(*tasks))
```

**After:**
```python
        tasks = [
            _scan_one(s, normalized_text, direction=direction, session_id=session_id)
            for s in self._ml_scanners
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        ml_results = [
            _normalize_gather_result(r, getattr(s, "name", "unknown"))
            for r, s in zip(raw_results, self._ml_scanners)
        ]
```

The `zip` pairs each result with its corresponding scanner for name extraction. Order is preserved by `asyncio.gather`.

### 5. `inspect()` outer handler (L325)

**Before:**
```python
        except Exception as exc:
            return PipelineResult(
                safe=False,
                findings=(),
                errors=(str(exc),),
            )
```

**After:**
```python
        except BaseException as exc:
            if not isinstance(exc, Exception):
                _logger.warning(
                    "Non-Exception caught at inspect() boundary: %s: %s",
                    type(exc).__name__,
                    exc,
                )
            error_msg = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            return PipelineResult(
                safe=False,
                findings=(),
                errors=(error_msg,),
            )
```

The `isinstance` guard ensures existing `Exception` subclasses continue to be handled silently (preserving current behavior). Only `BaseException`-only subclasses (`CancelledError`, `KeyboardInterrupt`, `SystemExit`) trigger the warning log. The error format matches `_scan_one` and `_normalize_gather_result` — bare `CancelledError()` produces `"CancelledError"` rather than an empty string.

### Invariants preserved

- **Pipeline never throws** — strengthened: now covers all exception types, not just `Exception` subclasses.
- **Fail-mode enforcement** — unchanged: `_compute_safe` still sees errored `ScanResult` objects from cancelled scanners, triggering degraded-mode blocking.
- **Scanner isolation** — strengthened: `_scan_one` + `return_exceptions=True` provides two-layer isolation.
- **No new dependencies** — `logging` is stdlib.

## Test plan

### New file: `tests/adversarial/pipeline/test_cancel_mid_gather.py`

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_inspect_catches_cancelled_error` | Scanner raises `asyncio.CancelledError`. `inspect()` returns `PipelineResult` (not raises), `safe is False`, error string mentions "CancelledError" |
| 2 | `test_scan_one_isolates_cancelled_scanner` | Call `_scan_one` with a scanner that raises `CancelledError`. Returns errored `ScanResult` (not raises), `error` contains "CancelledError" |
| 3 | `test_gather_return_exceptions_isolates_failure` | Two scanners: one raises `CancelledError`, other returns normally. `inspect()` returns `PipelineResult` with healthy scanner's findings in `result.findings` and cancelled scanner's error in `result.scanner_results[i].error` (contains "CancelledError") |
| 4 | `test_keyboard_interrupt_caught_at_boundary` | Scanner raises `KeyboardInterrupt`. `inspect()` returns `PipelineResult` (not raises), `safe is False` |
| 5 | `test_cancelled_error_logged` | Patch `petasos.pipeline._logger.warning`. Patch `Pipeline._inspect_inner` to raise `asyncio.CancelledError`. Call `inspect()`. Assert warning was emitted with `"CancelledError"` in the log args |
| 6 | `test_mid_gather_cancel_full_pipeline` | Full pipeline. Scanner blocks on an `asyncio.Event` (started-event signals readiness, proceed-event gates completion). Test awaits started-event, then calls `task.cancel()`, then sets proceed-event. Assert task result is `PipelineResult` (not raised `CancelledError`), `safe is False` |

### Test architecture notes

- Tests 1–4 use a stub scanner class (inline in the test file) whose `scan()` raises the target exception. No mocking of pipeline internals.
- Test 5 patches `Pipeline._inspect_inner` to raise `CancelledError` directly, so the exception reaches the `inspect()` outer handler where `_logger.warning` fires. This is necessary because scanner-raised `CancelledError` is caught by `_scan_one` (D2) and never reaches `inspect()`.
- Test 6 uses event-based synchronization for deterministic cancellation timing: scanner sets a "started" event then awaits a "proceed" event. The test awaits "started" to confirm the scanner is inside the gather, calls `task.cancel()`, then sets "proceed" to unblock. This eliminates `asyncio.sleep` race conditions.
- Test 2 calls `_scan_one` directly (it's a module-level function, not a private method — importable).
- Test 5 patches `petasos.pipeline._logger.warning` via `unittest.mock.patch`.

## Test command

```bash
C:/python310/python.exe -m pytest tests/adversarial/pipeline/test_cancel_mid_gather.py -v
```

## Done when

- [ ] `_scan_one` catches `BaseException`, not `Exception`
- [ ] `asyncio.gather` uses `return_exceptions=True` with post-gather normalization via `_normalize_gather_result`
- [ ] `inspect()` outer handler catches `BaseException`, not `Exception`
- [ ] `CancelledError` at the `inspect()` boundary is logged as a warning (non-`Exception` types only)
- [ ] `import logging` + `_logger` added to `pipeline.py`
- [ ] All 6 tests pass
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] Existing test suite passes (no regressions)
- [ ] `pytest --cov` confirms new `BaseException` branches in `_scan_one`, `_normalize_gather_result`, and `inspect()` are covered

## Out of scope

- **Shielding individual scanners from cancellation.** Scanners should be cancellable; the fix catches the cancellation, not prevents it.
- **`TaskGroup` migration.** Python 3.11 `TaskGroup` has better cancellation semantics but would be a larger refactor across the gather pattern. Separate ticket.
- **Other `except Exception` sites in `_inspect_inner`.** Per D4, stages 5c/6/7/etc. are downstream of gather and already protected by D2/D3. Separate ticket if a future finding targets them.
- **`wait_for` internal cancellation mechanics.** On Python 3.12+, `asyncio.wait_for` uses `cancel()`/`uncancel()` internally for timeouts. The `except BaseException` in `_scan_one` is outside `wait_for` and does not interfere with this protocol — `wait_for` catches its own internal `CancelledError` and re-raises as `TimeoutError` before `_scan_one`'s handler runs.
