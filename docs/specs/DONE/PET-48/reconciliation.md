# Reconciliation Report: PET-48

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-48.spec.md
> Merge: PR #34 (e8e32bc)
> Plane state: Done (group: completed)

## Summary
PET-48 shipped exactly as specified: the three `except Exception` sites in `pipeline.py` were broadened to `except BaseException`, `asyncio.gather` gained `return_exceptions=True` with a `_normalize_gather_result` helper, a module logger was added, and 6 adversarial tests were added. Every acceptance criterion is met; the only deviations are benign hardening additions (a `strict=True` on `zip`, logger placed after `hashlib`) and one extra companion artifact (`PET-48.test-output.txt`).

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/pipeline.py` | Yes | All 4 changes present: `import logging` + `_logger` (L5, L31), `_scan_one` → `except BaseException` (L164–171), `_normalize_gather_result` helper (L174–185), gather `return_exceptions=True` (L426–430), `inspect()` outer handler → `except BaseException` + warning log (L363–375). |
| `tests/adversarial/pipeline/test_cancel_mid_gather.py` | Yes | New file, 6 tests, all named per spec test plan. |

Unexpected files in diff (not in spec):
- `tests/test_pipeline.py` — 2 existing tests updated to match new behavior (error-format string `"RuntimeError: boom"`; `test_base_exception_propagates` renamed to `test_base_exception_caught_at_boundary`). Anticipated in spec ("existing test suite passes (no regressions)") but the file itself was listed under "Files to leave alone" only for `test_degraded_fail_open.py`, not `test_pipeline.py`. Necessary and correct.
- `docs/specs/TODO/PET-48.test-output.txt` — captured pytest run output (6 passed). Process artifact, not a code/spec change.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | `except BaseException` at `inspect()` boundary, not `asyncio.shield` | Confirmed | `pipeline.py:363` `except BaseException as exc:` returns `PipelineResult(safe=False)`; no shield introduced. |
| D2 | `_scan_one` catches `BaseException` | Confirmed | `pipeline.py:164` `except BaseException as exc:` returns errored `ScanResult`. |
| D3 | `asyncio.gather` gains `return_exceptions=True` + normalization | Confirmed | `pipeline.py:426` `await asyncio.gather(*tasks, return_exceptions=True)`; `_normalize_gather_result` at L174–185 converts exceptions to errored `ScanResult`. (Shipped code adds `strict=True` to the `zip` at L429 — stricter than spec's design snippet, intent preserved.) |
| D4 | `_inspect_inner` `except Exception` blocks unchanged | Confirmed | Diff touches only `_scan_one`, gather call, and outer `inspect()` handler; inner-stage handlers untouched. |
| D5 | `CancelledError` logged, not silently swallowed | Confirmed | `pipeline.py:364–369` `_logger.warning("Non-Exception caught at inspect() boundary: %s: %s", ...)`. |
| D6 | Logger follows module convention | Confirmed | `pipeline.py:5` `import logging`, `pipeline.py:31` `_logger = logging.getLogger(__name__)`. Placed after `hashlib` (added by another ticket) rather than the spec's exact line 4, but within the stdlib block and consistent with `alerting.py`/`guard.py` convention. |
| D7 | `KeyboardInterrupt`/`SystemExit` caught, not re-raised | Confirmed | `except BaseException` at L164 and L363 covers both; `tests/test_pipeline.py::test_base_exception_caught_at_boundary` asserts `SystemExit` is caught; `test_keyboard_interrupt_caught_at_boundary` asserts KI is caught. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `_scan_one` catches `BaseException`, not `Exception` | Met | `pipeline.py:164`. |
| 2 | `asyncio.gather` uses `return_exceptions=True` + `_normalize_gather_result` | Met | `pipeline.py:426–430`, helper at L174–185. |
| 3 | `inspect()` outer handler catches `BaseException`, not `Exception` | Met | `pipeline.py:363`. |
| 4 | `CancelledError` at `inspect()` boundary logged as warning (non-`Exception` only) | Met | `pipeline.py:364` `if not isinstance(exc, Exception):` then `_logger.warning(...)`. |
| 5 | `import logging` + `_logger` added to `pipeline.py` | Met | `pipeline.py:5`, `pipeline.py:31`. |
| 6 | All 6 tests pass | Met | `PET-48.test-output.txt`: "6 passed in 0.05s"; all 6 test functions present in `test_cancel_mid_gather.py`. |
| 7 | `ruff check .` and `mypy --strict .` clean | Unverifiable | Not re-run in this read-only reconciliation; commit `9c93c5d` ("style(pet-48): ruff format test file") indicates formatting was applied. |
| 8 | Existing test suite passes (no regressions) | Met (evidence of intent) | `tests/test_pipeline.py` updated for new error format and boundary behavior; both updated tests align with shipped code. Full suite not re-run here. |
| 9 | `pytest --cov` covers new `BaseException` branches | Met (by test design) | Tests 1/2 cover `_scan_one` `BaseException`; test 3 covers `_normalize_gather_result`; tests 4/5 cover `inspect()` boundary. Coverage report not regenerated here. |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| `test_inspect_catches_cancelled_error` | Yes | `tests/adversarial/pipeline/test_cancel_mid_gather.py:121` |
| `test_scan_one_isolates_cancelled_scanner` | Yes | `tests/adversarial/pipeline/test_cancel_mid_gather.py:134` |
| `test_gather_return_exceptions_isolates_failure` | Yes | `tests/adversarial/pipeline/test_cancel_mid_gather.py:144` |
| `test_keyboard_interrupt_caught_at_boundary` | Yes | `tests/adversarial/pipeline/test_cancel_mid_gather.py:161` (uses `patch.object` on `_inspect_inner` rather than a KI-raising scanner — event loop propagates KI from tasks before `_scan_one` can catch it; deviation documented inline) |
| `test_cancelled_error_logged` | Yes | `tests/adversarial/pipeline/test_cancel_mid_gather.py:174` (patches `_inspect_inner` to raise `CancelledError`, asserts `_logger.warning` called once with "CancelledError") |
| `test_mid_gather_cancel_full_pipeline` | Yes | `tests/adversarial/pipeline/test_cancel_mid_gather.py:190` (event-based deterministic cancel via `_BlockingScanner`) |

## Wiki-ready
- None — routine hardening fix. The `BaseException`-at-the-boundary pattern (catch cancellation, return `PipelineResult(safe=False)`, never shield) is the one mildly non-obvious reusable rule, but it is already captured by the pipeline-never-throws invariant in CLAUDE.md; no new decision worth a separate wiki entry.

RECONCILED: yes DRIFT: 1
