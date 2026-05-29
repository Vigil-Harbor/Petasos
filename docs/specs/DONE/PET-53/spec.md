# PET-53 Spec: Callback Isolation

**Tickets:** PET-53 (PIPE-06), PET-21 (AUD-02), PET-19 (ALRT-04), PET-18 (ALRT-03), PET-20 (AUD-01)
**Priority:** Medium · **OWASP:** ASI07
**Parent:** PET-14 · **Blocks:** PET-12 (release)

---

## Goal

Harden the callback and state-management boundaries in the audit and alerting subsystems so that (1) no callback exception — including `BaseException` subclasses — escapes into the pipeline, (2) the cross-session burst detector counts distinct sessions accurately even under ring-buffer eviction pressure, and (3) audit sequence numbers never reset to zero after session TTL pruning. All five findings are in the premium hooks layer; pipeline core logic is unchanged.

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/premium/audit.py` | (AUD-02) Add `import logging` + `_logger`. Remove `raise RuntimeError(...)` in `emit()` L62; catch `BaseException`, log, store error in `_last_callback_error`; add `last_callback_error` property. (AUD-01) Replace per-session `_sequence_counters` with `_global_sequence: int`. Remove `_NONE_SENTINEL`, `_last_emit_time`, `_prune_stale()`. |
| `petasos/premium/alerting.py` | (ALRT-04) Change callback handler `except Exception` → `except BaseException` at L165; store errors in `_callback_errors` list; add `callback_errors` property. (ALRT-03) Add `_cross_session_tracker: dict[str, float]` for accurate distinct session counting in `_check_cross_session_burst()`; prune in `_prune_stale()`. Remove dead `_NONE_SENTINEL` (L30). |
| `petasos/pipeline.py` | (PIPE-06) In Stages 10–11, after calling audit/alert hooks, read callback errors from the emitter/manager and append to the pipeline errors list. Keep existing `except Exception` wrappers as defense-in-depth. |
| `tests/adversarial/pipeline/test_callback_isolation.py` | New file — 15 adversarial tests (3 per finding). |
| `tests/test_audit.py` | Update 6 existing tests for changed callback and sequence behavior. |

### Files to leave alone

- `petasos/_types.py` — `AuditEvent`, `Alert`, `PipelineResult` unchanged
- `petasos/config.py` — no config surface changes
- `petasos/premium/escalation.py` — not in callback path
- `petasos/premium/frequency.py` — not in callback path
- `petasos/premium/guard.py` — not in callback path
- `petasos/premium/profiles/` — not in callback path
- `petasos/scanners/` — unchanged
- `petasos/normalize.py` — unchanged
- `tests/test_alerting.py` — existing callback test (`test_callback_exception_logs_and_continues`) already expects swallow-and-continue behavior; no changes needed
- `tests/adversarial/pipeline/test_cancel_mid_gather.py` — PET-48 tests, unrelated

## Decisions

### D1: Catch `BaseException`, not just `Exception`, in callback handlers

Both `audit.py` and `alerting.py` call user-supplied callbacks (`on_audit`, `on_alert`). These are arbitrary code — they could raise `KeyboardInterrupt`, `SystemExit`, or `CancelledError` (if the callback is async-unaware or wrapping async code). The pipeline-never-throws invariant requires catching all exception types. This is consistent with PET-48's `except BaseException` at the `inspect()` boundary.

### D2: Callback errors stored, not re-raised — pipeline reads them after the call

`audit.py` currently re-raises callback exceptions as `RuntimeError`. This propagates to the pipeline's `except Exception` wrapper in Stage 10, which catches it and appends to errors. The re-raise is unnecessary and dangerous (a `BaseException` would escape).

New pattern: `emit()` catches `BaseException`, logs via `_logger.error(exc_info=True)`, stores the error string in `self._last_callback_error: str | None` (cleared at the top of each `emit()` call). The error format includes the exception type name: `f"on_audit callback ({type(exc).__name__}): {exc}"` — consistent with PET-48's convention and necessary because `str(BaseException())` subclasses can be empty. `AuditEmitter` exposes the value via a public `last_callback_error` property. Pipeline's `_premium_audit_hook()` reads it after calling `emit()` and returns it. Stage 10 appends non-None return values to the errors list.

Same pattern for alerting: `evaluate()` catches `BaseException` per callback invocation, logs, accumulates in `self._callback_errors: list[str]` (cleared at the top of each `evaluate()` call). `AlertManager` exposes the list via a public `callback_errors` property. Pipeline's `_premium_alert_hook()` reads it and returns it. Stage 11 extends the errors list. This return-value pattern is a spec-level addition not in the original brief, chosen because re-raise is unsafe for `BaseException` types.

The pipeline's existing `except Exception` blocks on Stages 10–11 remain as defense-in-depth — they catch non-callback exceptions from `emit()` or `evaluate()` itself (e.g., a bug in `_build_payload`). The design relies on synchronous callback execution within Python's cooperative async model — no `await` point separates the `evaluate()` call from the `callback_errors` read, so concurrent `inspect()` calls cannot interleave.

### D3: Global monotonic sequence replaces per-session counters

Per-session sequence counters are deleted by `_prune_stale()` when a session exceeds `session_ttl_seconds`. If the session reconnects, its sequence restarts at 0 — a silent break in the monotonic chain that makes tamper detection unreliable.

Fix: a single `_global_sequence: int` increments across all sessions. Benefits:
- Immune to TTL pruning (nothing to prune)
- Total ordering across sessions (useful for audit log reconstruction)
- Simpler implementation (remove `_sequence_counters`, `_last_emit_time`, `_prune_stale()`, `_NONE_SENTINEL`)

Trade-off: per-session gap detection requires the consumer to filter by `session_id` and check ordering within each group. This is acceptable — the consumer already has `session_id` on every `AuditEvent`.

### D4: Cross-session tracker alongside ring buffer, not replacing it

The ring buffer (`deque(maxlen=...)`) in `_check_cross_session_burst()` evicts the oldest entries when full, losing unique session IDs from the distinct count. A separate `dict[str, float]` maps `session_id → last_seen_timestamp` without the maxlen constraint.

Distinct sessions are counted from the tracker dict (entries within the time window), not from the ring buffer. The ring buffer is kept for its role in the `_ring_buffers` dict (shared pruning in `_prune_stale()`). The tracker dict is pruned of stale entries both inline (in `_check_cross_session_burst()`) and in `_prune_stale()`, with a hard cap of `max(2 * alert_ring_buffer_capacity, alert_cross_session_burst_count)` entries to bound memory while guaranteeing the cap never prevents burst detection.

### D5: `_prune_stale()` in alerting.py gains cross-session tracker cleanup

The existing `_prune_stale()` method in `AlertManager` cleans up cooldowns, per-minute deques, per-hour deques, session deques, critical deques, and ring buffers. The new `_cross_session_tracker` dict is added to this cleanup: entries where `(now - ts) > cross_session_burst_window_seconds` are evicted. This prevents the tracker from growing unbounded between bursts.

### D6: audit.py gains a logger

`audit.py` currently has no logger. Add `import logging` and `_logger = logging.getLogger(__name__)` following the same placement convention as `alerting.py`, `guard.py`, and `profiles/__init__.py`: import in the stdlib block, `_logger` after the last real import and before `TYPE_CHECKING`.

## Design

### 1. Add logger to `audit.py`

Add `import logging` to the stdlib import block (between `import time` L3 and `import uuid` L4). Add `_logger = logging.getLogger(__name__)` after the `AuditEvent` import (L8) and before the `TYPE_CHECKING` block (L10):

```python
import logging
```

```python
_logger = logging.getLogger(__name__)
```

### 2. AUD-02 + AUD-01: `audit.py` `__init__` and `emit()` rewrite

**`__init__` changes (consolidated).** After `self._on_audit = on_audit` (L28), remove L29–30 (`_sequence_counters`, `_last_emit_time`). Add in their place:

```python
        self._global_sequence: int = 0
        self._last_callback_error: str | None = None
```

**Remove:** `_NONE_SENTINEL` (L17), `_prune_stale()` method (L106–111).

**Add a public property** for pipeline access (after `emit()`):

```python
    @property
    def last_callback_error(self) -> str | None:
        return self._last_callback_error
```

**`emit()` rewrite.** Clear `_last_callback_error` at the top, use global sequence, catch `BaseException` in callback:

**Before (L38–64):**
```python
        now_mono = time.monotonic()
        self._prune_stale(now_mono)

        session_key: object = session_id if session_id is not None else _NONE_SENTINEL
        seq = self._sequence_counters.get(session_key, 0)
        ...
        self._sequence_counters[session_key] = seq + 1
        self._last_emit_time[session_key] = now_mono

        if self._on_audit is not None:
            try:
                self._on_audit(event)
            except Exception as exc:
                raise RuntimeError(f"on_audit callback failed: {exc}") from exc
```

**After:**
```python
        self._last_callback_error = None
        seq = self._global_sequence
        ...
        self._global_sequence = seq + 1

        if self._on_audit is not None:
            try:
                self._on_audit(event)
            except BaseException as exc:
                _logger.error("on_audit callback failed: %s", exc, exc_info=True)
                self._last_callback_error = (
                    f"on_audit callback ({type(exc).__name__}): {exc}"
                    if str(exc)
                    else f"on_audit callback ({type(exc).__name__})"
                )
```

Three changes: (1) `_last_callback_error` cleared at the top of `emit()`, consistent with D2 and the alerting pattern. (2) `except Exception` → `except BaseException`, log instead of re-raise. (3) Error format includes type name: `"on_audit callback (RuntimeError): boom"` — matches PET-48's convention; handles empty `str()` on `BaseException` subclasses like bare `CancelledError()`.

Remove `now_mono`, `_prune_stale()` call, `session_key` computation, `_sequence_counters` update, `_last_emit_time` update. The `time.monotonic()` call is no longer needed in `emit()` (`time.time()` is still used for `AuditEvent.timestamp`).

### 3. ALRT-04: Callback isolation in `alerting.py` `evaluate()`

**Remove dead code:** `_NONE_SENTINEL` (L30) — defined but never referenced in alerting.py.

**Add to `__init__` (after L54):** `self._callback_errors: list[str] = []`

**Add a public property** for pipeline access:

```python
    @property
    def callback_errors(self) -> tuple[str, ...]:
        return tuple(self._callback_errors)
```

**In `evaluate()`, add at the top (after L79):** `self._callback_errors = []`

**Change callback handler (L162–169):**

**Before:**
```python
            if self._on_alert is not None:
                try:
                    self._on_alert(candidate)
                except Exception:
                    _logger.exception(
                        "on_alert callback failed for rule_id=%s",
                        candidate.rule_id,
                    )
```

**After:**
```python
            if self._on_alert is not None:
                try:
                    self._on_alert(candidate)
                except BaseException as exc:
                    _logger.exception(
                        "on_alert callback failed for rule_id=%s",
                        candidate.rule_id,
                    )
                    self._callback_errors.append(
                        f"on_alert callback ({candidate.rule_id}, {type(exc).__name__}): {exc}"
                        if str(exc)
                        else f"on_alert callback ({candidate.rule_id}, {type(exc).__name__})"
                    )
```

Three changes: (1) `except Exception` → `except BaseException as exc`. (2) Append to `_callback_errors` with type name (PET-48 convention). (3) Handle empty `str(exc)` for `BaseException` subclasses.

### 4. ALRT-03: Cross-session tracker in `alerting.py`

**Add to `__init__` (after the ring buffer init):** `self._cross_session_tracker: dict[str, float] = {}`

**In `_check_cross_session_burst()`, replace the distinct session counting and alert construction (L301–321).** The "Before" block covers L301–321 (distinct count + alert body), not just L301–304, because the alert body at L312/316 references `recent_sessions` which is replaced by the tracker.

**Before (L301–321):**
```python
        window = self._config.alert_cross_session_burst_window_seconds
        recent_sessions = {sid for ts, sid in buf if (now - ts) <= window}

        if len(recent_sessions) >= self._config.alert_cross_session_burst_count:
            return Alert(
                alert_id=uuid.uuid4().hex,
                timestamp=time.time(),
                rule_id="cross_session_burst",
                severity="high",
                session_id=session_id,
                message=(
                    f"Cross-session burst: {len(recent_sessions)} distinct sessions in {window}s"
                ),
                context=MappingProxyType(
                    {
                        "distinct_sessions": len(recent_sessions),
                        "window_seconds": window,
                        "threshold": self._config.alert_cross_session_burst_count,
                    }
                ),
            )
        return None
```

**After:**
```python
        self._cross_session_tracker[session_id] = now
        window = self._config.alert_cross_session_burst_window_seconds
        stale_sids = [
            sid for sid, ts in self._cross_session_tracker.items() if (now - ts) > window
        ]
        for sid in stale_sids:
            del self._cross_session_tracker[sid]
        tracker_cap = max(
            2 * self._config.alert_ring_buffer_capacity,
            self._config.alert_cross_session_burst_count,
        )
        if len(self._cross_session_tracker) > tracker_cap:
            sorted_entries = sorted(self._cross_session_tracker.items(), key=lambda x: x[1])
            for sid, _ in sorted_entries[: len(self._cross_session_tracker) - tracker_cap]:
                del self._cross_session_tracker[sid]

        distinct_count = len(self._cross_session_tracker)
        if distinct_count >= self._config.alert_cross_session_burst_count:
            return Alert(
                alert_id=uuid.uuid4().hex,
                timestamp=time.time(),
                rule_id="cross_session_burst",
                severity="high",
                session_id=session_id,
                message=(
                    f"Cross-session burst: {distinct_count} distinct sessions in {window}s"
                ),
                context=MappingProxyType(
                    {
                        "distinct_sessions": distinct_count,
                        "window_seconds": window,
                        "threshold": self._config.alert_cross_session_burst_count,
                    }
                ),
            )
        return None
```

The ring buffer append (L299) is unchanged. The tracker dict replaces the `recent_sessions` set comprehension as the source of truth for distinct session counting. Stale entries (outside window) are pruned inline. The hard cap is `max(2 * ring_buffer_capacity, burst_count)` — this guarantees the cap never prevents burst detection even when `2 * capacity < burst_count`. The `distinct_count` local replaces all references to `len(recent_sessions)` in the alert body.

**In `_prune_stale()`, add after the ring buffer cleanup block (after L411):**

```python
        burst_window = self._config.alert_cross_session_burst_window_seconds
        stale_tracker_keys = [
            sid
            for sid, ts in self._cross_session_tracker.items()
            if (now - ts) > burst_window
        ]
        for sid in stale_tracker_keys:
            del self._cross_session_tracker[sid]
```

### 5. PIPE-06: Pipeline reads callback errors via public properties

**Change `_premium_audit_hook` (L569–579) return type and body:**

**Before:**
```python
    async def _premium_audit_hook(
        self,
        result: PipelineResult,
        session_id: str | None,
        freq_result: FrequencyUpdateResult | None,
    ) -> None:
        if not self._check_premium("audit"):
            return
        if not self._config.audit_enabled:
            return
        self._audit_emitter.emit(result, session_id, freq_result)
```

**After:**
```python
    async def _premium_audit_hook(
        self,
        result: PipelineResult,
        session_id: str | None,
        freq_result: FrequencyUpdateResult | None,
    ) -> str | None:
        if not self._check_premium("audit"):
            return None
        if not self._config.audit_enabled:
            return None
        self._audit_emitter.emit(result, session_id, freq_result)
        return self._audit_emitter.last_callback_error
```

**Change `_premium_alert_hook` (L581–591) return type and body:**

**Before:**
```python
    async def _premium_alert_hook(
        self,
        result: PipelineResult,
        session_id: str | None,
        freq_result: FrequencyUpdateResult | None,
    ) -> None:
        if not self._check_premium("alerting"):
            return
        if not self._config.alert_enabled:
            return
        self._alert_manager.evaluate(result, session_id, freq_result)
```

**After:**
```python
    async def _premium_alert_hook(
        self,
        result: PipelineResult,
        session_id: str | None,
        freq_result: FrequencyUpdateResult | None,
    ) -> tuple[str, ...]:
        if not self._check_premium("alerting"):
            return ()
        if not self._config.alert_enabled:
            return ()
        self._alert_manager.evaluate(result, session_id, freq_result)
        return self._alert_manager.callback_errors
```

**Change Stage 10 (L503–507):**

**Before:**
```python
        # Stage 10: Premium audit hook
        try:
            await self._premium_audit_hook(result, session_id, freq_result)
        except Exception as exc:
            errors.append(f"audit hook: {exc}")
```

**After:**
```python
        # Stage 10: Premium audit hook
        try:
            audit_cb_error = await self._premium_audit_hook(result, session_id, freq_result)
            if audit_cb_error is not None:
                errors.append(audit_cb_error)
        except Exception as exc:
            errors.append(f"audit hook: {exc}")
```

**Change Stage 11 (L509–513):**

**Before:**
```python
        # Stage 11: Premium alert hook
        try:
            await self._premium_alert_hook(result, session_id, freq_result)
        except Exception as exc:
            errors.append(f"alert hook: {exc}")
```

**After:**
```python
        # Stage 11: Premium alert hook
        try:
            alert_cb_errors = await self._premium_alert_hook(result, session_id, freq_result)
            errors.extend(alert_cb_errors)
        except Exception as exc:
            errors.append(f"alert hook: {exc}")
```

### Invariants preserved

- **Pipeline never throws** — strengthened: callback `BaseException` types now caught at the module level (defense layer 1) in addition to the pipeline hook wrapper (defense layer 2) and the `inspect()` boundary (defense layer 3, from PET-48).
- **Fail-mode enforcement** — unchanged: callback errors don't affect `_compute_safe`.
- **Audit event construction** — unchanged: the `AuditEvent` is constructed before the callback runs; callback failure doesn't affect the returned event.
- **Alert surviving list** — unchanged: the alert is added to `surviving` before the callback runs; callback failure doesn't remove it.
- **No new dependencies** — `logging` already imported in `alerting.py`; added to `audit.py` (stdlib).

## Existing test changes

### `tests/test_audit.py` — 6 tests updated

| Test | Current behavior | New behavior |
|------|-----------------|--------------|
| `test_callback_raises_valueerror_wrapped_as_runtime` (L227–233) | Expects `pytest.raises(RuntimeError)` | Assert `emit()` returns normally; `emitter.last_callback_error` contains `"on_audit callback (ValueError)"` |
| `test_callback_raises_generic_exception_wrapped` (L235–241) | Expects `pytest.raises(RuntimeError)` | Assert `emit()` returns normally; `last_callback_error` set |
| `test_different_sessions_independent` (L185–191) | s1=0, s2=0, s1=1 (per-session) | s1=0, s2=1, s1=2 (global) |
| `test_none_session_uses_dedicated_counter` (L194–200) | None=0, s1=0, None=1 | None=0, s1=1, None=2 |
| `test_multiple_sessions_interleaved` (L273–282) | s1=[0,1,2], s2=[0,1,2], s3=[0,1,2] | s1=[0,3,6], s2=[1,4,7], s3=[2,5,8] |
| `test_stale_session_pruning` (L314–328) | Asserts pruned session key deleted from `_sequence_counters` | Rewrite: assert `_global_sequence` continues monotonically; pruning of `_sequence_counters` no longer exists |

### `tests/test_alerting.py` — 0 tests updated

Existing `test_callback_exception_logs_and_continues` (L611–623) already expects the exception to be swallowed and processing to continue. The change from `except Exception` to `except BaseException` is backward-compatible with `ValueError` (an `Exception` subclass). No assertion changes needed.

## Test plan

### New file: `tests/adversarial/pipeline/test_callback_isolation.py`

| # | Finding | Test | Asserts |
|---|---------|------|---------|
| 1 | AUD-02 | `test_audit_callback_runtime_error_swallowed` | Pipeline with premium active, `on_audit=raises(RuntimeError)`. `inspect()` returns `PipelineResult`, `safe` unchanged by callback, `"on_audit callback"` in `result.errors` |
| 2 | AUD-02 | `test_audit_callback_base_exception_swallowed` | `on_audit=raises(KeyboardInterrupt)`. Same assertions as test 1 |
| 3 | AUD-02 | `test_audit_callback_error_logged` | Patch `petasos.premium.audit._logger.error`. `on_audit=raises(ValueError)`. Assert `_logger.error` called with `exc_info=True` |
| 4 | ALRT-04 | `test_alert_callback_runtime_error_in_errors` | Pipeline with premium active, `on_alert=raises(RuntimeError)`, trigger a high-severity finding. `"on_alert callback"` in `result.errors` |
| 5 | ALRT-04 | `test_alert_callback_base_exception_swallowed` | `on_alert=raises(KeyboardInterrupt)`. Pipeline returns normally, error captured |
| 6 | ALRT-04 | `test_alert_callback_error_logged` | Patch `petasos.premium.alerting._logger`. `on_alert=raises(ValueError)`. Assert `_logger.exception` called |
| 7 | PIPE-06 | `test_audit_error_reaches_pipeline_result` | End-to-end: construct Pipeline with `on_audit=raises(RuntimeError)`. Call `inspect()`. Assert `PipelineResult.errors` contains the callback error string |
| 8 | PIPE-06 | `test_alert_error_reaches_pipeline_result` | End-to-end: construct Pipeline with `on_alert=raises(RuntimeError)` and trigger a finding. Assert `PipelineResult.errors` contains the alert callback error |
| 9 | PIPE-06 | `test_both_callbacks_fail_both_errors_in_result` | Both `on_audit` and `on_alert` raise. Both errors present in `PipelineResult.errors` |
| 10 | ALRT-03 | `test_cross_session_burst_accurate_under_eviction` | `alert_ring_buffer_capacity=5, alert_cross_session_burst_count=4, cooldown=0.001`. Flood 6 distinct sessions (s1–s6) with findings, then push s6 two more times. At push 8, ring buffer holds only {s4,s5,s6}→3 distinct (old code: no burst). Tracker holds {s1–s6}→6 distinct ≥ 4 (new code: burst fires). Assert the last `evaluate()` returns a `cross_session_burst` alert |
| 11 | ALRT-03 | `test_cross_session_tracker_time_window_eviction` | Send bursts in two windows separated by > `alert_cross_session_burst_window_seconds`. Assert sessions from the first window don't count in the second |
| 12 | ALRT-03 | `test_cross_session_tracker_cap_bounds_memory` | `alert_ring_buffer_capacity=50`. Flood 200 distinct sessions. Assert `len(manager._cross_session_tracker) <= 100` (2x cap) |
| 13 | AUD-01 | `test_sequence_continues_after_ttl_prune_boundary` | Emit events for session A, advance time past TTL, emit for session A again. Assert new `sequence_number > last_seen_sequence_number` (no reset to 0) |
| 14 | AUD-01 | `test_sequence_global_monotonic_across_sessions` | Interleave emits for sessions A, B, C. Collect all `sequence_number` values. Assert strictly increasing (no duplicates, no resets) |
| 15 | AUD-01 | `test_sequence_never_zero_after_first_emit` | Emit once (seq=0). Advance past TTL. Emit again for same session. Assert `sequence_number > 0` |

### Test architecture notes

- Tests 1–9 require a premium-activated pipeline. The existing `tests/adversarial/conftest.py` provides `minimal_pipeline` and `degraded_pipeline` — neither activates premium. Tests 1–9 construct their own `Pipeline` instances with a patched `LicenseValidator.validate` returning `(LicenseState.VALID, mock_claims)` where `mock_claims` has a future `expiry`. This follows the pattern used in `tests/test_license.py` for premium-gated tests.
- Tests 10–12 test `AlertManager` directly (unit tests), not through the pipeline. This isolates the ring-buffer fix from premium gating.
- Tests 13–15 test `AuditEmitter` directly. With `_prune_stale()` removed, time mocking is only needed for `time.time()` (event timestamps). Sequence continuity is verified by checking `_global_sequence` values.
- Tests 1–2 and 4–5 use helper functions that raise the target exception type. Lambdas can raise via helper; a simple `def _raise_runtime(e): raise RuntimeError("boom")` is cleaner.

## Test command

```bash
C:/python310/python.exe -m pytest tests/adversarial/pipeline/test_callback_isolation.py tests/test_audit.py tests/test_alerting.py -v
```

## Done when

- [ ] `audit.py` `emit()` catches `BaseException` from callback, does not re-raise
- [ ] `audit.py` has `import logging` + `_logger`
- [ ] `audit.py` stores callback error in `_last_callback_error`; pipeline reads it and appends to `PipelineResult.errors`
- [ ] `alerting.py` `evaluate()` catches `BaseException` from callback (was `Exception`)
- [ ] `alerting.py` stores callback errors in `_callback_errors`; pipeline reads them and extends `PipelineResult.errors`
- [ ] `audit.py` sequence numbering uses `_global_sequence` — no per-session counters, no `_prune_stale()`
- [ ] `alerting.py` `_check_cross_session_burst()` counts distinct sessions from `_cross_session_tracker` dict, not from ring buffer
- [ ] `_cross_session_tracker` pruned by time window and capped at `max(2 * alert_ring_buffer_capacity, alert_cross_session_burst_count)`
- [ ] Pipeline Stages 10–11 capture callback errors via return values from hook methods
- [ ] All 15 new adversarial tests pass
- [ ] 6 existing `test_audit.py` tests updated and passing
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] Existing test suite passes (no regressions)

## Out of scope

- **Callback circuit breaker.** A circuit breaker (disable callback after N failures for M seconds) would be more robust but is a separate design decision. Swallowing is the minimal fix.
- **Async callback support.** Callbacks are sync today (`Callable[[AuditEvent], None]`). Async callbacks would require `await` and change the `emit()` signature. Separate ticket.
- **PET-50 (PIPE-03 scanner timeout).** Different failure mode — scanner-level, not callback-level.
- **Per-session sequence with LRU persistence.** The brief mentions this as an alternative to global monotonic. Global is simpler and meets the acceptance criteria. Per-session LRU could be a follow-up if consumers need per-session gap detection.
- **Changing `_compute_safe` for callback errors.** Callback failures are observability failures, not scan failures. They belong in `PipelineResult.errors` but should not flip `safe` to `False`.
