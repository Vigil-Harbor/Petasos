# PET-30 Edge-Cases Review — Round 1

## Findings

### F-1: `update()` re-creates a fresh SessionState for a tombstoned-and-evicted session
**Severity:** P1
**Where:** spec Design section 3 and frequency.py:99-117
After TTL eviction, `update()` creates a brand-new `SessionState(last_score=0.0, terminated=False)` for a tombstoned session. The live state then shadows the tombstone in `is_terminated()`. The guard protects via `_derive_tier()` but `FrequencyUpdateResult` says `terminated=False`.
**Suggested fix:** Add tombstone check at top of `update()`, before Step 2, returning `tier="tier3", terminated=True` immediately if session is tombstoned.

### F-2: `_evict_one()` preferentially evicts terminated sessions but does not record tombstones
**Severity:** P1
**Where:** spec Design section 3 and frequency.py:211-228
`_evict_one()` preferentially evicts terminated sessions. If the tombstone was missed on write (future code path, schema upgrade), the terminated state is lost permanently.
**Suggested fix:** Add defensive tombstone write in `_evict_one()` before deletion for terminated candidates.

### F-3: `max_terminated_tombstones=1` allows immediate tombstone loss
**Severity:** P2
Config allows `1` which provides near-zero protection in multi-session scenarios.
**Suggested fix:** Document minimum effective value or add test.

### F-4: Re-termination does not refresh FIFO position
**Severity:** P2
`OrderedDict.__setitem__` for existing key preserves insertion order. Re-terminated sessions age out faster than expected.
**Suggested fix:** Use `move_to_end()` on re-termination.

### F-5: Empty string session_id accepted in tombstone set
**Severity:** P3
Pre-existing issue, not introduced by this spec.

### F-6: No test for `_evict_one()` recording tombstone
**Severity:** P2
If F-2 fix is adopted, the defensive write is untested.

### F-7: `update()` returns `RATE_LIMITED_RESULT` for tombstoned session
**Severity:** P2
Under rate-limit conditions, tombstoned session gets `tier="none"`. Fixed by F-1's tombstone check.

### F-8: Config round-trip works mechanically
**Severity:** P4 (informational)
`from_dict`/`to_dict` handle new field automatically.

### F-9: Threading / concurrency for `is_terminated` + `get_state`
**Severity:** P4
Single-process assumption is consistent with existing codebase.

### F-10: No test for double-termination idempotency
**Severity:** P3
Test plan doesn't cover `terminate_session()` called twice.

## Summary
P0: 0 | P1: 2 | P2: 4 | P3: 2 | P4: 2

STATUS: RED P0=0 P1=2 P2=4 P3=2 P4=2
