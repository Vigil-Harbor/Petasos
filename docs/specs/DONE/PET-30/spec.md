# PET-30 — FREQ-02: Terminated Session State Loss via TTL Eviction

**Brief:** `docs/briefs/PET-30-freq-02-terminated-state-loss.md`
**Finding:** FREQ-02 | **Priority:** High | **OWASP:** ASI07
**Parent:** PET-14 | **Blocks:** PET-12 (release), PET-34 (GUARD-01)

> PET-34 added to Blocks: the brief body describes PET-30 as "a precondition for PET-34" (brief L185–186) but the brief header lists only PET-12. This spec formalizes the dependency so Plane tracks it.

---

## Goal

Add a bounded tombstone set to `FrequencyTracker` so that terminated session IDs survive both TTL eviction and LRU eviction. Wire both `update()` (to prevent zombie session re-creation) and `ToolCallGuard._derive_tier()` (to block tool calls) to check the tombstone, closing the attack chain where an evicted terminated session becomes indistinguishable from a never-seen session.

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/premium/frequency.py` | Add `OrderedDict` import (module-level). Add `_terminated_ids` tombstone set, `is_terminated()` method, `force_reset()` method, `_enforce_tombstone_cap()` method, `tombstone_count` property. Update `__init__()`, `update()` (tombstone early-return + tombstone write), `terminate_session()`, `reset()`, `clear()`, `_evict_one()` (defensive tombstone write). |
| `petasos/premium/guard.py` | Update `_derive_tier()` to call `is_terminated()` before `get_state()`. |
| `petasos/config.py` | Add `max_terminated_tombstones: int = 10_000` field with validation. |

### New files

| File | Purpose |
|------|---------|
| `tests/adversarial/frequency/test_terminated_state_loss.py` | Adversarial tests: tombstone survives TTL/LRU, guard blocks after eviction |
| `tests/test_frequency_tombstone.py` | Unit tests: tombstone CRUD, bounding, reset/force_reset/clear semantics |

> No `__init__.py` in `tests/adversarial/frequency/` — matching the convention of sibling adversarial test directories (none have `__init__.py`; pytest discovers via rootdir).

### Files to leave alone

- `petasos/premium/escalation.py` — no changes needed; `evaluate_tier()` is score-based, not session-aware.
- `petasos/premium/audit.py`, `petasos/premium/alerting.py` — tombstone is internal to frequency/guard; no audit/alert surface changes.
- `petasos/premium/profiles.py` — profiles don't interact with tombstones.
- `petasos/pipeline.py` — pipeline delegates to guard; no pipeline-level change.
- `_evict_one()` preferential eviction of terminated sessions (L218–226) is retained — with tombstones, this preference is benign because the defensive tombstone write (Design section 9) ensures the terminated state persists even after eviction.
- Existing `tests/test_frequency.py`, `tests/test_guard.py` — existing tests continue to pass unchanged; new tests go in dedicated files to avoid merge conflicts with parallel PET-14 work.

## Decisions

### Decision 1: Tombstone set, not database
Petasos is in-process with no persistence layer. An `OrderedDict[str, None]` provides bounded FIFO eviction with O(1) lookup and O(1) insertion. If persistence is needed later (across process restarts), that's a separate feature (explicitly out of scope per brief).

### Decision 2: `reset()` does not clear tombstone
The invariant is **"terminated stays terminated."** Administrative override via `force_reset()` is explicit. This prevents an attacker from calling `reset()` to un-terminate themselves. The brief calls this out as a load-bearing design choice.

### Decision 3: FIFO bounding with position refresh on re-termination
Terminated sessions are checked, not "accessed" in an LRU sense. FIFO eviction drops the oldest terminations first. On re-termination of an already-tombstoned session, `move_to_end()` refreshes the FIFO position — this prevents a repeatedly-attacked session from aging out of the tombstone set prematurely. Without the refresh, `OrderedDict.__setitem__` for an existing key preserves the original insertion position, meaning the tombstone would be evicted based on the first termination time, not the most recent.

### Decision 4: Guard checks tombstone first
`_derive_tier()` calls `is_terminated()` before `get_state()`. This handles the critical case where session state has been evicted but the termination record persists. Without this ordering, the `get_state() is None → "none"` path runs first and the tombstone is never consulted.

### Decision 5: `update()` checks tombstone before creating sessions
`update()` checks the tombstone set before Step 2 ("get or create session"). If a tombstoned session calls `update()` after eviction, it returns immediately with `tier="tier3", terminated=True` instead of re-creating a fresh `SessionState`. Without this check, a fresh `SessionState(terminated=False)` would shadow the tombstone in `is_terminated()`'s two-phase lookup, and `FrequencyUpdateResult` would report `terminated=False` — inconsistent with the guard's `_derive_tier()` result. This also prevents tombstoned sessions from consuming slots in `_sessions` or triggering rate-limit responses.

### Decision 6: Refuted status acknowledged
This finding was refuted during triage (TTL-based resurrection requires the attacker to wait `session_ttl_seconds` and re-establish). The fix ships regardless — the invariant "terminated stays terminated" is load-bearing for the GUARD-01 chain (PET-34) and should hold unconditionally.

### Decision 7: Test plan expanded from brief's 9 to 20
The brief specifies 9 tests. This spec expands to 21 for additional boundary coverage: tombstone cap at 1, double-termination idempotency, defensive `_evict_one()` tombstone write, `update()` early-return for tombstoned sessions, FIFO position refresh on re-termination. The brief's `test_guard_derive_tier_checks_tombstone` (unit test of `_derive_tier()`) is subsumed by adversarial tests 3–4 (`test_guard_blocks_after_ttl_eviction`, `test_guard_blocks_after_lru_eviction`), which exercise the full `evaluate()` chain end-to-end.

## Design

### 1. Module-level import (`petasos/premium/frequency.py`)

Add `OrderedDict` to the existing `collections` import at L5:

```python
from collections import OrderedDict, deque
```

### 2. Tombstone data structure (`petasos/premium/frequency.py`)

Add to `FrequencyTracker.__init__()` at L86 (after `self._creation_timestamps`):

```python
self._terminated_ids: OrderedDict[str, None] = OrderedDict()
self._max_terminated: int = config.max_terminated_tombstones
```

The `OrderedDict` is keyed by session ID with `None` values — used as an ordered set. Insertion order tracks age for FIFO eviction.

### 3. `is_terminated()` public method (`petasos/premium/frequency.py`)

New method after `get_state()` (after L185):

```python
def is_terminated(self, session_id: str) -> bool:
    state = self._sessions.get(session_id)
    if state is not None:
        return state.terminated
    return session_id in self._terminated_ids
```

Two-phase check: live session state first (authoritative while session exists), then tombstone set (survives eviction). Returns `False` for never-seen sessions.

### 4. Tombstone check at top of `update()`

Insert after Step 1 (TTL eviction, L90–97) and before Step 2 (get or create session, L99):

```python
# Step 1.5: Tombstone early-return — do not re-create evicted terminated sessions
if session_id not in self._sessions and session_id in self._terminated_ids:
    sentinel = self._config.tier3_threshold
    return FrequencyUpdateResult(
        previous_score=sentinel,
        current_score=sentinel,
        tier="tier3",
        terminated=True,
    )
```

This prevents re-creation of a `SessionState` for a tombstoned session. The guard and `update()` now agree on the session's terminated status. The double condition (`not in _sessions` and `in _terminated_ids`) ensures live sessions with tombstones (the belt-and-suspenders case) still follow the normal update path, which hits the existing Step 4 early-return at L125–132.

The sentinel scores use `tier3_threshold` (default 50.0) rather than `0.0`. This is critical for alerting compatibility: `AlertManager._check_tier_escalation()` computes `evaluate_tier(previous_score)` — using `0.0` would yield `"none"`, which differs from the current `"tier3"`, firing a spurious escalation alert on every `update()` call for a tombstoned session. Using `tier3_threshold` ensures `evaluate_tier()` returns `"tier3"` for both previous and current scores, so `previous_tier == current_tier` and no alert fires. The true historical score is lost when the `SessionState` is evicted; `tier3_threshold` is a conservative lower bound — the actual score at termination was at least this high.

### 5. Record termination in tombstone set

**In `update()` at L164–165** — when tier3 is reached:

```python
if tier == "tier3":
    state.terminated = True
    self._add_tombstone(session_id)
```

**In `terminate_session()` at L186–189** — explicit termination:

```python
def terminate_session(self, session_id: str) -> None:
    state = self._sessions.get(session_id)
    if state is not None:
        state.terminated = True
    self._add_tombstone(session_id)
```

Note: `terminate_session()` records the tombstone even if the session state is already evicted. This handles the edge case where `terminate_session()` is called after TTL eviction.

### 6. `_add_tombstone()` helper with FIFO refresh

Private method that consolidates tombstone insertion logic:

```python
def _add_tombstone(self, session_id: str) -> None:
    if session_id in self._terminated_ids:
        self._terminated_ids.move_to_end(session_id)
    else:
        self._terminated_ids[session_id] = None
    self._enforce_tombstone_cap()
```

`move_to_end()` refreshes the FIFO position for re-terminated sessions. For new tombstones, a simple insertion is used. This ensures that a repeatedly-attacked session always has its tombstone at the "newest" position and won't be evicted prematurely.

### 7. Tombstone bounding (`_enforce_tombstone_cap`)

Private method:

```python
def _enforce_tombstone_cap(self) -> None:
    while len(self._terminated_ids) > self._max_terminated:
        self._terminated_ids.popitem(last=False)  # FIFO: drop oldest
```

Called after every tombstone insertion. `popitem(last=False)` removes the first-inserted entry (oldest tombstone).

### 8. Protect tombstones from `reset()`, expose `force_reset()`

**`reset()` at L191–192** — unchanged behavior for session state, but tombstone is preserved:

```python
def reset(self, session_id: str) -> None:
    self._sessions.pop(session_id, None)
```

**New `force_reset()`** — administrative override:

```python
def force_reset(self, session_id: str) -> None:
    self._sessions.pop(session_id, None)
    self._terminated_ids.pop(session_id, None)
```

### 9. Defensive tombstone write in `_evict_one()`

Update `_evict_one()` at L211–228 to record the tombstone before evicting a terminated session:

```python
if terminated_candidate is not None:
    sid = terminated_candidate[0]
    if sid not in self._terminated_ids:
        self._terminated_ids[sid] = None
        self._enforce_tombstone_cap()
    del self._sessions[sid]
elif oldest_candidate is not None:
    del self._sessions[oldest_candidate[0]]
```

This makes `_evict_one()` self-healing: even if a tombstone was missed during termination (future code path, schema upgrade), eviction records it before deleting the `SessionState`. The conditional check (`sid not in self._terminated_ids`) avoids calling `_add_tombstone()` for already-tombstoned sessions — that helper uses `move_to_end()` which would refresh the FIFO position, artifically making the tombstone appear younger and skewing eviction order against other tombstones. For already-tombstoned sessions, the existing tombstone at its original FIFO position is correct.

### 10. Update `clear()`

`clear()` at L194–196 must also clear the tombstone set:

```python
def clear(self) -> None:
    self._sessions.clear()
    self._creation_timestamps.clear()
    self._terminated_ids.clear()
```

### 11. `tombstone_count` property

The `size` property at L198–199 stays as-is — it counts active sessions, not tombstones. Add a separate read-only property:

```python
@property
def tombstone_count(self) -> int:
    return len(self._terminated_ids)
```

### 12. Guard integration (`petasos/premium/guard.py`)

Update `_derive_tier()` at L170–185:

```python
def _derive_tier(self, session_id: str) -> str:
    if self._frequency_tracker.is_terminated(session_id):
        return "tier3"
    state = self._frequency_tracker.get_state(session_id)
    if state is None:
        return "none"
    if self._profile and self._profile.tier_thresholds:
        t = self._profile.tier_thresholds
        if state.last_score >= t.tier3:
            return "tier3"
        if state.last_score >= t.tier2:
            return "tier2"
        if state.last_score >= t.tier1:
            return "tier1"
        return "none"
    return evaluate_tier(state.last_score, self._config)
```

The `is_terminated()` check runs first. If `is_terminated()` returns `False`, the session is known to be non-terminated (both live state and tombstone were checked), so the previous `if state.terminated: return "tier3"` check (old L174) is removed — it would be unreachable dead code after `is_terminated()` already inspects the live state's `terminated` field.

> **Brief divergence:** The brief's Remediation section 5 retains the `if state.terminated: return "tier3"` check as belt-and-suspenders. This spec removes it because `is_terminated()` already consults the live state's `terminated` field in its first phase — retaining the check creates unreachable dead code that misleads future readers into thinking there's a path that bypasses `is_terminated()`.

### 13. Config surface (`petasos/config.py`)

Add field to `PetasosConfig` after `max_new_sessions_per_minute` (L81):

```python
max_terminated_tombstones: int = 10_000
```

Add validation in `__post_init__()` after the `max_new_sessions_per_minute` block (after L135):

```python
if (
    not isinstance(self.max_terminated_tombstones, int)
    or isinstance(self.max_terminated_tombstones, bool)
    or self.max_terminated_tombstones <= 0
):
    raise ValueError(
        f"max_terminated_tombstones must be a positive integer, "
        f"got {self.max_terminated_tombstones!r}"
    )
```

## Test Plan

### Adversarial tests (`tests/adversarial/frequency/test_terminated_state_loss.py`)

These tests reproduce the attack sequences from the brief.

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_terminated_survives_ttl_eviction` | Terminate session via tier3, advance time past `session_ttl_seconds`, call `update()` to trigger TTL eviction, verify `is_terminated()` returns `True`. |
| 2 | `test_terminated_survives_lru_eviction` | Terminate session, flood new sessions to trigger `_evict_one()`, verify `is_terminated()` returns `True` after the terminated session's `SessionState` is evicted from `_sessions`. |
| 3 | `test_guard_blocks_after_ttl_eviction` | Full chain: terminate session, evict via TTL, call `ToolCallGuard.evaluate()`, assert `allowed=False`, `tier="tier3"`. |
| 4 | `test_guard_blocks_after_lru_eviction` | Full chain: terminate session, evict via LRU pressure, call `ToolCallGuard.evaluate()`, assert `allowed=False`, `tier="tier3"`. |
| 5 | `test_reset_does_not_resurrect_terminated` | Terminate session, call `reset()`, verify `is_terminated()` still returns `True` and guard blocks. |
| 6 | `test_update_returns_tier3_for_tombstoned_session` | Terminate session, evict via TTL, call `update(session_id, ["petasos.syntactic.injection.test"])` with non-empty rule_ids. Assert `result.tier == "tier3"`, `result.terminated == True`, `result.current_score == config.tier3_threshold` (sentinel — score not accumulated beyond threshold). Verify session is NOT re-created in `_sessions`. |
| 7a | `test_tombstoned_update_no_spurious_alert` | Full pipeline with alerting callback: terminate session, evict via TTL, call `update()` for the tombstoned session. Assert no tier-escalation alert fires (sentinel `previous_score=tier3_threshold` matches `current_score`, so `previous_tier == current_tier`). |
| 7 | `test_evict_one_defensive_tombstone_write` | Directly inject `SessionState(terminated=True)` into `_sessions` without a corresponding tombstone. Trigger `_evict_one()`. Verify `is_terminated()` returns `True` after eviction. |

### Unit tests (`tests/test_frequency_tombstone.py`)

| # | Test | Asserts |
|---|------|---------|
| 8 | `test_terminate_session_sets_tombstone` | `terminate_session()` adds ID to `_terminated_ids`. Verify via `is_terminated()`. |
| 9 | `test_terminate_session_tombstone_when_state_missing` | Call `terminate_session()` on a session that was already evicted (not in `_sessions`). Verify `is_terminated()` returns `True`. |
| 10 | `test_tier3_update_sets_tombstone` | Accumulate score past tier3 via `update()`. Verify `is_terminated()` returns `True`. |
| 11 | `test_reset_preserves_tombstone` | Terminate, `reset()`, verify `is_terminated()` returns `True` and session not in `_sessions`. |
| 12 | `test_force_reset_clears_tombstone` | Terminate, `force_reset()`, verify `is_terminated()` returns `False`. |
| 13 | `test_tombstone_bounded_fifo` | Set `max_terminated_tombstones=3`. Terminate 4 sessions. Verify the first is evicted, last 3 remain. |
| 14 | `test_tombstone_cap_at_one` | Set `max_terminated_tombstones=1`. Terminate 2 sessions. Verify only the second survives. |
| 15 | `test_clear_clears_tombstones` | Terminate sessions, `clear()`, verify `is_terminated()` returns `False` and `tombstone_count == 0`. |
| 16 | `test_is_terminated_false_for_unknown` | `is_terminated()` returns `False` for a session ID that was never seen. |
| 17 | `test_is_terminated_true_for_live_terminated` | Terminate session (state still in `_sessions`), verify `is_terminated()` returns `True` via the live state path. |
| 18 | `test_tombstone_count_property` | Verify `tombstone_count` reflects the number of entries in `_terminated_ids`. |
| 19 | `test_double_termination_idempotent` | Call `terminate_session("s1")` twice. Verify `is_terminated("s1")` returns `True`, `tombstone_count == 1`, and the FIFO position is refreshed (tombstone is at the end). |
| 20 | `test_config_max_terminated_tombstones_validation` | `PetasosConfig(max_terminated_tombstones=0)` raises `ValueError`. Same for `-1`, `True`, `"foo"`. |

## Test Command

```bash
python -m pytest tests/adversarial/frequency/test_terminated_state_loss.py tests/test_frequency_tombstone.py tests/test_frequency.py tests/test_guard.py -v
```

Full suite regression:

```bash
python -m pytest --tb=short
```

## Done When

- [ ] `OrderedDict` import added at module level in `frequency.py`
- [ ] `_terminated_ids: OrderedDict[str, None]` added to `FrequencyTracker.__init__()`
- [ ] `is_terminated()` public method added to `FrequencyTracker`
- [ ] `_add_tombstone()` private helper with `move_to_end()` refresh
- [ ] `_enforce_tombstone_cap()` private method added
- [ ] `update()` checks tombstone before Step 2 — returns `tier3` immediately for tombstoned sessions
- [ ] `update()` records termination in tombstone set on tier3
- [ ] `terminate_session()` records in tombstone set (even if session state missing)
- [ ] `reset()` preserves tombstone; `force_reset()` clears both
- [ ] `clear()` clears tombstone set
- [ ] `_evict_one()` defensively records tombstone before evicting terminated sessions
- [ ] `tombstone_count` property added
- [ ] `max_terminated_tombstones: int = 10_000` added to `PetasosConfig` with validation
- [ ] `ToolCallGuard._derive_tier()` checks `is_terminated()` before `get_state()`; removes unreachable `state.terminated` check
- [ ] All 21 tests pass
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of Scope

- **Persistent termination across process restarts** — no persistence layer exists today; separate feature if needed.
- **Tombstone synchronization across multiple tracker instances** — Petasos is single-process.
- **Drawbridge backport** — uncoupled project, own ticket if needed.
- **Tombstone expiry policy** — FIFO bounding is sufficient; time-based expiry adds complexity without clear benefit.
- **PET-34 (GUARD-01) implementation** — this spec is the precondition; PET-34 gets its own brief/spec.
- **Audit trail for tombstone operations** — tombstone add/evict events are internal bookkeeping, not security-relevant state changes. If audit coverage is desired, it belongs in a follow-up.
- **`session_id` input validation** (empty string) — pre-existing gap in `update()`; not introduced or worsened by this change.

## Deferred (P2+)

Items surfaced in round 1 review that are addressed inline or acknowledged:

- **`max_terminated_tombstones=1` behavior** — valid config, provides near-zero protection in multi-session scenarios. Documented via test 14 (`test_tombstone_cap_at_one`) to make the behavior explicit. No minimum floor enforced — operational choice for the deployer.
- **`PetasosConfig` validation bool-guard pattern asymmetry** — this spec follows the stricter alerting-era pattern (`isinstance(..., bool)` check) rather than the adjacent session-management pattern. The stricter pattern is objectively more correct; harmonizing the older fields is a separate cleanup.
