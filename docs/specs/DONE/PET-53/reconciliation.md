# Reconciliation Report: PET-53

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-53.spec.md
> Merge: #42 (dee93f5)
> Plane state: Done (group: completed)

## Summary
PET-53 (callback isolation for audit/alerting) shipped in PR #42 / commit dee93f5 with the spec's three source files changed exactly as designed: `BaseException`-catching callback isolation with public error properties, global monotonic audit sequence, and a cross-session tracker dict. All 15 new adversarial tests and the 6 renamed `test_audit.py` tests are present on disk; the only deviations are two extra test files swept into the PR (a string-match fix and a Python-3.13 event-loop modernization) that the spec did not name.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/premium/audit.py` | Yes | logger added; `_global_sequence` + `_last_callback_error`; `last_callback_error` property; `except BaseException`; `_NONE_SENTINEL`, `_sequence_counters`, `_last_emit_time`, `_prune_stale()` removed. Matches spec exactly. |
| `petasos/premium/alerting.py` | Yes | logger added; `_cross_session_tracker` dict + `_callback_errors`/`callback_errors` property; `except BaseException`; `_NONE_SENTINEL` removed; tracker pruned inline + in `_prune_stale()` + capped. Matches spec. |
| `petasos/pipeline.py` | Yes | `_premium_audit_hook` → `str | None`, `_premium_alert_hook` → `tuple[str, ...]`; Stages 10–11 append/extend errors. Matches spec. |
| `tests/adversarial/pipeline/test_callback_isolation.py` | Yes | New file, all 15 named tests present (3 per finding). |
| `tests/test_audit.py` | Yes | 6 tests updated (renamed to global-sequence / swallowed semantics). |

Unexpected files in diff (not in spec):
- `tests/test_premium_integration.py` — 2 assertion strings updated (`"audit hook"`→`"on_audit callback"`, `"alert hook"`→`"on_alert callback"`) to track the new error-message format. Consequential to the change but not enumerated in spec's "Files to change".
- `tests/test_presidio_scanner.py` — 16 call sites migrated `asyncio.get_event_loop().run_until_complete()` → `asyncio.run()` for Python 3.13 compat. Unrelated to PET-53's threat model; swept in via the lint/3.13 fixup commits.
- `docs/specs/TODO/PET-53.test-output.txt` — added test-run audit trail (ship-spec artifact, not code).

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | Catch `BaseException` not `Exception` in callback handlers | Confirmed | audit.py:62 `except BaseException as exc`; alerting.py:170 `except BaseException as exc` |
| D2 | Callback errors stored (not re-raised), pipeline reads after call | Confirmed | audit.py:43,63-68 (`_last_callback_error` cleared at top, set in handler) + 33-35 property; pipeline.py:616 returns it; alerting.py:84 clears, 175 appends, 56-58 property; pipeline.py:629 returns it |
| D3 | Global monotonic sequence replaces per-session counters | Confirmed | audit.py:30 `_global_sequence`; :44,57 use/increment; `_sequence_counters`/`_last_emit_time`/`_prune_stale` absent (grep empty) |
| D4 | Cross-session tracker dict alongside ring buffer | Confirmed | alerting.py:53 `_cross_session_tracker`; :311 records; :313-325 prune+cap `max(2*capacity, burst_count)`; :327-328 counts from tracker |
| D5 | `_prune_stale()` gains cross-session tracker cleanup | Confirmed | alerting.py:436-440 prune entries where `(now-ts) > burst_window` |
| D6 | audit.py gains a logger | Confirmed | audit.py:3 `import logging`, :11 `_logger = logging.getLogger(__name__)` |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `emit()` catches `BaseException`, does not re-raise | Met | audit.py:62-68; no `raise` in handler |
| 2 | audit.py has `import logging` + `_logger` | Met | audit.py:3,11 |
| 3 | audit.py stores callback error; pipeline reads + appends | Met | audit.py:64-68; pipeline.py:533-535,616 |
| 4 | alerting.py `evaluate()` catches `BaseException` | Met | alerting.py:170 |
| 5 | alerting.py stores callback errors; pipeline reads + extends | Met | alerting.py:175; pipeline.py:541-542,629 |
| 6 | audit.py uses `_global_sequence`, no per-session counters / `_prune_stale()` | Met | audit.py:30,44,57; removed symbols grep-empty |
| 7 | `_check_cross_session_burst()` counts from tracker dict | Met | alerting.py:327-328 `distinct_count = len(self._cross_session_tracker)` |
| 8 | tracker pruned by window + capped at `max(2*capacity, burst_count)` | Met | alerting.py:313-325, 436-440 |
| 9 | Stages 10–11 capture callback errors via return values | Met | pipeline.py:533-535 (append), 541-542 (extend) |
| 10 | All 15 new adversarial tests pass | Met | test_callback_isolation.py defines all 15 named tests; PET-53.test-output.txt records pass |
| 11 | 6 existing `test_audit.py` tests updated & passing | Met | test_audit.py:184,193,226,237,277,318 renamed to global-sequence/swallowed semantics |
| 12 | `ruff check .` and `mypy --strict .` clean | Unverifiable | Not re-run (read-only reconcile); fixup commits 5e45fe7/acc7222/404b191 address lint/format |
| 13 | Existing test suite passes (no regressions) | Unverifiable | Not re-run; PET-53.test-output.txt records the targeted suite green |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| test_audit_callback_runtime_error_swallowed | Yes | test_callback_isolation.py:108 |
| test_audit_callback_base_exception_swallowed | Yes | test_callback_isolation.py:119 |
| test_audit_callback_error_logged | Yes | test_callback_isolation.py:129 |
| test_alert_callback_runtime_error_in_errors | Yes | test_callback_isolation.py:147 |
| test_alert_callback_base_exception_swallowed | Yes | test_callback_isolation.py:159 |
| test_alert_callback_error_logged | Yes | test_callback_isolation.py:170 |
| test_audit_error_reaches_pipeline_result | Yes | test_callback_isolation.py:187 |
| test_alert_error_reaches_pipeline_result | Yes | test_callback_isolation.py:195 |
| test_both_callbacks_fail_both_errors_in_result | Yes | test_callback_isolation.py:204 |
| test_cross_session_burst_accurate_under_eviction | Yes | test_callback_isolation.py:225 |
| test_cross_session_tracker_time_window_eviction | Yes | test_callback_isolation.py:250 |
| test_cross_session_tracker_cap_bounds_memory | Yes | test_callback_isolation.py:273 |
| test_sequence_continues_after_ttl_prune_boundary | Yes | test_callback_isolation.py:293 |
| test_sequence_global_monotonic_across_sessions | Yes | test_callback_isolation.py:301 |
| test_sequence_never_zero_after_first_emit | Yes | test_callback_isolation.py:310 |
| test_audit.py 6 updated tests | Yes (renamed) | test_audit.py:184,193,226,237,277,318 |
| test_alerting.py callback test (spec: 0 updates) | Diverged | diff renamed `test_callback_exception_raises_runtime`→`test_callback_exception_swallowed`; spec claimed no changes needed. Later superseded on master by PET-76 (#44, 239ca2a) → `test_callback_exception_logs_and_continues` (test_alerting.py:611). Post-PET-53 churn, behavior still correct. |

## Wiki-ready
- D2/D3 callback-error return-value pattern: hooks return errors (`str | None` / `tuple[str, ...]`) for the pipeline to fold into `PipelineResult.errors` instead of re-raising — a reusable convention for the never-throws invariant, layered with PET-48's `inspect()` boundary. Constrains future hook signatures.
- D4 cross-session tracker with `max(2*ring_buffer_capacity, burst_count)` cap: the cap formula is deliberately chosen so it can never suppress a legitimate burst even when `2*capacity < burst_count` — a non-obvious correctness constraint worth recording.

RECONCILED: yes DRIFT: 3
