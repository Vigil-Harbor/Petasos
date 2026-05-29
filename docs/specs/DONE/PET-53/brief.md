# Brief 7 — Callback Isolation

**Plane items:** PET-19 (ALRT-04), PET-21 (AUD-02), PET-53 (PIPE-06), PET-18 (ALRT-03), PET-20 (AUD-01)
**Files touched:** `petasos/premium/audit.py`, `petasos/premium/alerting.py`, `petasos/pipeline.py` (premium hook wrappers only)
**Priority:** medium (all)

## Findings

| ID | Severity | Attack | Current behavior | Remediation |
|----|----------|--------|------------------|-------------|
| AUD-02 | medium | `on_audit` raises `RuntimeError` | `emit()` (lines 58–62) wraps callback in try/except but *re-raises* RuntimeError — propagates to pipeline, breaking the never-throws invariant | Swallow all callback exceptions; log error; append to `PipelineResult.errors` |
| ALRT-04 | medium | `on_alert` raises under critical flood | Same pattern as AUD-02 — callback exception propagates | Same fix: swallow, log, append to errors |
| PIPE-06 | medium | Exception from any premium hook callback | Premium hooks in `_inspect_inner()` catch exceptions and append to errors, but sync callbacks within those hooks (audit/alert) can still propagate | Ensure every callback invocation in audit.py and alerting.py is fully isolated; pipeline hooks already catch, but defense-in-depth |
| ALRT-03 | medium | Flood cross_session_burst ring buffer | Distinct sessions evicted from ring buffer → burst detector under-counts | Use a separate `set()` for distinct session tracking alongside the ring buffer; the set grows up to `alert_cross_session_burst_count` + buffer |
| AUD-01 | medium | Reuse session_id after TTL prune → sequence resets to 0 | `_prune_stale()` deletes the per-session sequence counter; reconnecting session restarts at 0, breaking monotonic chain | Use a global monotonic counter (not per-session) or persist last-seen sequence per session in a bounded LRU even after TTL prune |

## Approach

**Callback isolation (AUD-02, ALRT-04, PIPE-06):** This is a single pattern applied consistently:

```python
# In audit.py emit() and alerting.py evaluate():
try:
    self._on_audit(event)  # or self._on_alert(alert)
except BaseException as exc:
    _logger.error("Callback failed: %s", exc, exc_info=True)
    # Do NOT re-raise — pipeline never throws
```

Remove the `raise` in `audit.py` line 62. Change `alerting.py` to match (it already swallows — verify). In `pipeline.py`, the premium hook wrappers already catch; add a comment documenting the defense-in-depth layering.

**ALRT-03 (burst buffer):** In `_check_cross_session_burst()`, maintain a `dict[str, float]` mapping `session_id → last_seen_timestamp` alongside the ring buffer. When the ring buffer evicts an entry, don't remove the session from the dict. Count distinct sessions from the dict entries within the time window. Cap the dict size at `2 * alert_ring_buffer_capacity` with LRU eviction.

**AUD-01 (sequence reset):** Replace the per-session sequence counter (`_sequences: dict[str, int]`) with a single `_global_sequence: int` that increments monotonically across all sessions. This is simpler, still tamper-evident (any gap indicates a dropped event), and immune to TTL-prune resets.

## Decisions carried forward

- **Global vs. per-session sequence:** Global sequence means you can't detect per-session gaps without correlating by session_id. This is acceptable — the audit consumer can group by session_id and check for ordering within that group. The global counter guarantees total ordering and eliminates the reset vulnerability.
- **Callback exception swallowing vs. circuit breaker:** Swallowing is the minimal fix. A future enhancement could add a circuit breaker (after N failures, disable the callback for M seconds). Out of scope for this brief.

## Done when

- [ ] `on_audit` raising `RuntimeError` → pipeline returns normally, error in `PipelineResult.errors`
- [ ] `on_alert` raising `RuntimeError` → same behavior
- [ ] 100 rapid triggers from distinct sessions → cross_session_burst alert fires with correct count
- [ ] Session TTL prune → reconnecting session gets sequence_number > last emitted (global monotonic)
- [ ] No callback exception propagates to `inspect()` caller under any circumstance
- [ ] >= 15 tests (3 per finding)
- [ ] `mypy --strict` clean

## Out of scope

- Callback circuit breaker / retry logic
- Async callback support (callbacks are sync today — async is a separate design decision)
- PET-50 (PIPE-03 scanner timeout) — different failure mode
