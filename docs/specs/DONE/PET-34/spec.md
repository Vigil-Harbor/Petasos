# PET-34 — GUARD-01: Tier 3 Session Bypass After LRU Eviction

## Goal

Prevent a terminated (tier 3) session from regaining tool-call access after its `SessionState` is evicted from `FrequencyTracker._sessions` via LRU cap or TTL expiry. The fix adds a persistent termination tombstone set in `FrequencyTracker` (the FREQ-02/PET-30 prerequisite) and a guard-side query in `ToolCallGuard._derive_tier()` that checks the tombstone before falling through to `get_state()`.

## Relationship to PET-30 (FREQ-02)

PET-30 shipped the tombstone infrastructure in `FrequencyTracker` (commit b8f9ad4): `_terminated_ids`, `is_terminated()`, `_add_tombstone()`, `_enforce_tombstone_cap()`, tombstone early-return in `update()`, defensive tombstone write in `_evict_one()`, and the guard-side `_derive_tier()` check. PET-34 hardens the TTL eviction path with a defensive tombstone write (discovered during spec review — see D7) and adds a test for the TTL+FIFO interaction. The two tickets are tracked separately because FREQ-02 is the core tombstone defense and GUARD-01 is the eviction-path hardening.

## Scope

### Files changed

| File | Change |
|------|--------|
| `petasos/premium/frequency.py` | Add `_terminated_ids: OrderedDict`, `is_terminated()`, `_add_tombstone()`, `_enforce_tombstone_cap()`, tombstone early-return in `update()`, defensive tombstone write in `_evict_one()` and TTL eviction |
| `petasos/premium/guard.py` | `_derive_tier()` checks `is_terminated()` before `get_state()` |
| `petasos/config.py` | Add `max_terminated_tombstones` config field with validation |
| `tests/test_frequency_tombstone.py` | 17 unit tests for tombstone lifecycle (13 test classes, 17 test functions) |
| `tests/adversarial/frequency/test_terminated_state_loss.py` | 9 adversarial tests for eviction-resistant termination + guard integration |

### Files left alone

- `petasos/premium/escalation.py` — no changes needed
- `petasos/premium/profiles.py` — not involved
- `petasos/premium/audit.py`, `petasos/premium/alerting.py` — not involved
- `tests/adversarial/guard/test_tool_smuggling.py` — GUARD-03 tests, unrelated

## Decisions

### D1: OrderedDict, not set+deque

The brief proposed `_terminated_set: set[str]` + `_terminated_ids: deque[str]` for O(1) lookup + FIFO ordering. The implementation uses `_terminated_ids: OrderedDict[str, None]` instead — it provides both O(1) lookup and insertion-ordered iteration in a single data structure, with `move_to_end()` for re-termination and `popitem(last=False)` for FIFO eviction. Simpler, fewer invariants to maintain.

### D2: Tombstone, not full state resurrection

When a terminated session is evicted, only the boolean termination fact survives in the tombstone set — not the full `SessionState` (score, rolling window, etc.). This avoids re-inflating stale scores and keeps the tombstone set lightweight (string keys only). `get_state()` still returns `None` for evicted sessions; the tombstone is queried separately via `is_terminated()`.

### D3: reset() preserves tombstones, force_reset() clears them

**Departs from brief.** The brief specified `reset()` should clear terminated state. We override that because allowing `reset()` to clear tombstones would create a bypass vector identical to the one PET-34 is designed to fix — an attacker who can trigger `reset()` could undo termination. `reset()` removes the session from `_sessions` but preserves its tombstone. `force_reset()` removes from both `_sessions` and `_terminated_ids` — this is the operator-level escape hatch for deliberate session rehabilitation.

### D4: Defensive tombstone write in _evict_one()

`_evict_one()` prefers evicting terminated sessions (they're blocked anyway, so evicting them has no user-facing impact). When evicting a terminated session, it writes a tombstone defensively if one doesn't already exist — but does NOT call `_add_tombstone()` (which calls `move_to_end()`), because refreshing the FIFO position during eviction would make the tombstone appear younger than it is. Instead, it directly inserts into `_terminated_ids` and calls `_enforce_tombstone_cap()`.

### D5: Tombstone early-return in update()

When `update()` is called for a session that has been evicted from `_sessions` but exists in `_terminated_ids`, it short-circuits with `tier3` / `terminated=True` and a sentinel score of `config.tier3_threshold`. This prevents re-creation of the session state and avoids spurious tier-escalation alerts (both `previous_score` and `current_score` are set to the same sentinel value). The sentinel score is synthetic — it may not match the session's original historical score. Future audit/analytics consumers should account for this.

### D6: Cap at max_terminated_tombstones (default 10,000)

**Departs from brief.** The brief proposed `max_sessions * 2` (default 2000) and the name `max_terminated_sessions`. We chose an independent field `max_terminated_tombstones` (default 10,000) for explicit operator control, decoupled from `max_sessions`, to avoid surprising cap changes when operators tune session limits. FIFO eviction of the oldest tombstone bounds memory while retaining defense for realistic attack windows.

### D7: Defensive tombstone write in TTL eviction (spec review finding)

Round 1 edge-cases review (F-1) identified a gap: if a tombstone is FIFO-evicted from `_terminated_ids` while the session is still in `_sessions` with `terminated=True`, subsequent TTL eviction deletes from `_sessions` without writing a defensive tombstone — leaving `is_terminated()` returning `False`. Attack sequence: terminate S → FIFO-evict S's tombstone (via many other terminations exceeding `max_terminated_tombstones`) → S expires via TTL → guard allows. Fix: the TTL eviction loop checks `state.terminated` before deleting each stale session and writes a defensive tombstone if one doesn't exist, using the same pattern as `_evict_one()` (direct insert, no `move_to_end()`).

### D8: is_terminated() is intentionally token-free

`is_terminated()` accepts a bare `session_id: str` without HMAC verification, unlike `get_state()`, `update()`, `terminate_session()`, and `reset()` which route through `_resolve_session_id()` and require a `SessionToken` when `session_secret` is configured. This is intentional: `is_terminated()` is a read-only boolean query with no state mutation. The guard's `_derive_tier()` calls it with the raw `session_id` from `evaluate()`, which is the correct internal-use pattern. `force_reset()` also accepts bare strings as an operator escape hatch.

## Design

### Layer 1: FrequencyTracker tombstone set (FREQ-02/PET-30)

```
FrequencyTracker.__init__:
    _terminated_ids: OrderedDict[str, None]  # FIFO insertion order
    _max_terminated: int                     # from config.max_terminated_tombstones

_add_tombstone(session_id):
    if exists: move_to_end (refresh FIFO position)
    else: insert
    _enforce_tombstone_cap()

_enforce_tombstone_cap():
    while len > _max_terminated: popitem(last=False)  # evict oldest

is_terminated(session_id) -> bool:
    state = _sessions.get(session_id)
    if state is not None: return state.terminated
    return session_id in _terminated_ids
```

Tombstone writes happen at four points:
1. `update()` — when tier3 is reached (`state.terminated = True`)
2. `terminate_session()` — explicit termination
3. `_evict_one()` — defensive write when evicting a terminated session
4. TTL eviction in `update()` — defensive write when TTL-expiring a terminated session (D7)

Tombstone clears happen at:
1. `force_reset()` — removes from both `_sessions` and `_terminated_ids`
2. `clear()` — empties everything including `_terminated_ids`

### Layer 2: Guard-side is_terminated() query (GUARD-01)

```
_derive_tier(session_id):
    if frequency_tracker.is_terminated(session_id):
        return "tier3"              # tombstone hit — block
    state = frequency_tracker.get_state(...)
    if state is None:
        return "none"               # genuinely unknown session
    ... existing threshold logic ...
```

The `is_terminated()` check comes first, before `get_state()`. This means:
- If the session is in `_sessions` with `terminated=True`, `is_terminated()` returns `True` (fast path via live state).
- If the session was evicted but has a tombstone, `is_terminated()` returns `True` (tombstone path).
- If the session is genuinely unknown (never seen or tombstone FIFO-evicted), `is_terminated()` returns `False`, and `get_state()` returns `None` -> tier "none".

### Layer 3: Config validation

`max_terminated_tombstones` is validated in `PetasosConfig.__post_init__()`:
- Must be a positive integer
- Must not be a bool (Python `bool` subclasses `int`)
- Defaults to 10,000

### Layer 4: TTL eviction defensive tombstone (D7)

In the TTL eviction loop (frequency.py `update()` Step 1), before deleting each stale session, check `state.terminated`. If terminated and not already in `_terminated_ids`, write a defensive tombstone:

```python
stale = [
    sid
    for sid, state in self._sessions.items()
    if now - state.last_update > self._session_ttl
]
for sid in stale:
    state = self._sessions[sid]
    if state.terminated and sid not in self._terminated_ids:
        self._terminated_ids[sid] = None
        self._enforce_tombstone_cap()
    del self._sessions[sid]
```

## Test plan

### Unit tests — tombstone lifecycle (`tests/test_frequency_tombstone.py`)

13 test classes, 17 test functions (test 20 has 5 sub-tests for config validation).

| # | Test | Asserts |
|---|------|---------|
| 8 | `test_terminate_session_sets_tombstone` | `terminate_session()` -> `is_terminated()` returns `True` |
| 9 | `test_terminate_session_tombstone_when_state_missing` | `terminate_session()` on never-seen session -> `is_terminated()` True, `get_state()` None |
| 10 | `test_tier3_update_sets_tombstone` | Score crosses tier3 -> `terminated=True`, `tombstone_count=1` |
| 11 | `test_reset_preserves_tombstone` | `reset()` removes from `_sessions`, tombstone persists |
| 12 | `test_force_reset_clears_tombstone` | `force_reset()` removes from both stores |
| 13 | `test_tombstone_bounded_fifo` | Cap at 3, 4th tombstone evicts oldest |
| 14 | `test_tombstone_cap_at_one` | Cap at 1, second evicts first |
| 15 | `test_clear_clears_tombstones` | `clear()` empties everything |
| 16 | `test_is_terminated_false_for_unknown` | Never-seen session -> `False` |
| 17 | `test_is_terminated_true_for_live_terminated` | Session in `_sessions` with `terminated=True` -> `True` |
| 18 | `test_tombstone_count_property` | Property tracks inserts/removals correctly |
| 19 | `test_double_termination_idempotent` | Re-terminate moves to end of FIFO, count unchanged |
| 20 | `test_config_max_terminated_tombstones_validation` | Zero/negative/bool/string all raise; positive int passes (5 sub-tests) |

### Adversarial tests — eviction-resistant termination (`tests/adversarial/frequency/test_terminated_state_loss.py`)

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_terminated_survives_ttl_eviction` | TTL eviction removes `_sessions` entry, tombstone persists |
| 2 | `test_terminated_survives_lru_eviction` | LRU flood evicts `_sessions` entry, tombstone persists |
| 3 | `test_guard_blocks_after_ttl_eviction` | `evaluate()` returns `allowed=False, tier=tier3` after TTL eviction |
| 4 | `test_guard_blocks_after_lru_eviction` | `evaluate()` returns `allowed=False, tier=tier3` after LRU flood |
| 5 | `test_reset_does_not_resurrect_terminated` | `reset()` + `evaluate()` still blocks |
| 6 | `test_update_returns_tier3_for_tombstoned_session` | `update()` on tombstoned session returns tier3, does NOT re-create session |
| 7a | `test_tombstoned_update_no_spurious_alert` | Both previous and current score = tier3_threshold (no tier-change alert) |
| 7 | `test_evict_one_defensive_tombstone_write` | Directly-injected terminated session gets tombstone during `_evict_one()` |
| 8 | `test_ttl_eviction_defensive_tombstone` | **NEW (D7).** `max_terminated_tombstones=1`, terminate S1, terminate S2 (FIFO-evicts S1 tombstone), TTL-expire S1 -> defensive tombstone written -> `is_terminated("s1")` is `True` |

### Mapping to brief's required tests

The brief proposed test files in `tests/unit/premium/` and `tests/adversarial/guard/`. We use the repo's established flat `tests/` layout and `tests/adversarial/frequency/` instead.

| Brief Test | Covered By |
|------------|------------|
| `test_tier3_survives_lru_eviction` | Tests 2 + 4 |
| `test_tier3_survives_ttl_eviction` | Tests 1 + 3 |
| `test_is_terminated_after_eviction` | Tests 1, 2 |
| `test_terminated_set_fifo_cap` | Test 13 |
| `test_reset_clears_terminated` | Tests 11 (preserve per D3), 12 (force clear) |
| `test_clear_clears_terminated` | Test 15 |
| `test_derive_tier_uses_is_terminated` | Tests 3, 4 |

## Test command

```
python -m pytest tests/test_frequency_tombstone.py tests/adversarial/frequency/test_terminated_state_loss.py tests/test_guard.py -v
```

## Done when

- [x] `FrequencyTracker` has `_terminated_ids: OrderedDict` and `is_terminated()` method
- [x] `_evict_one()` preserves terminated IDs via defensive tombstone write
- [ ] TTL eviction writes defensive tombstone for terminated sessions (D7)
- [x] `_derive_tier()` queries `is_terminated()` before `get_state()`
- [x] FIFO cap on terminated set enforced and tested
- [x] `reset()` preserves and `force_reset()` clears terminated state
- [x] `clear()` clears terminated state
- [ ] Test 8 (TTL defensive tombstone) passes
- [x] All other tests pass (17 unit + 9 adversarial = 26 test functions)
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of scope

- Distributed / multi-process session state (Petasos is in-process only)
- Drawbridge backport (Drawbridge has partial mitigation via `lastEmittedTier`; separate ticket if needed)
- Frequency tracker refactoring beyond the terminated set (tracked under FREQ-02 / PET-30)
- Audit trail for eviction events (useful but not blocking for this fix)
- Input validation for empty-string session_id (defense-in-depth gap, low priority)
