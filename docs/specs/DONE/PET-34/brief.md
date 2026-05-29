# PET-34 — GUARD-01: Tier 3 Session Bypass After LRU Eviction

**Plane:** PET-34 · **Finding:** GUARD-01 · **Priority:** Urgent  
**OWASP:** ASI02 — Tool-use manipulation  
**Parent:** PET-14 · **Blocks:** PET-12 (release)  
**Status:** Backlog → ready-for-dev  
**Chains from:** PET-30 (FREQ-02) — guard fix requires frequency fix to land first

---

## Problem

`ToolCallGuard.evaluate()` checks tier 3 / terminated status at Step 3 (L103–111 of `petasos/premium/guard.py`) by calling `_derive_tier(session_id)`. That method delegates to `FrequencyTracker.get_state()` at L171 of `guard.py`. If `get_state` returns `None`, `_derive_tier` returns `"none"` (L172–173), and the guard falls through to Step 4 (exempt check) and beyond — treating the session as clean.

`FrequencyTracker` evicts sessions in two ways: passive TTL eviction (L90–97 of `frequency.py`) during `update()`, and LRU cap eviction via `_evict_one()` (L211–228) when `max_sessions` is exceeded. Both delete the session entry from `self._sessions`, including the `terminated=True` flag. After eviction, `get_state()` returns `None` for what was a terminated session.

Attack sequence:
1. Attacker accumulates a score above tier 3 threshold on session S — S is marked `terminated=True`.
2. Attacker floods `max_sessions` new sessions (or waits for TTL expiry).
3. Session S is evicted from the tracker's `_sessions` dict.
4. Attacker calls `evaluate("exec", {...}, S)` — `_derive_tier` returns `"none"` because `get_state(S)` is `None`.
5. The tool call is allowed despite S having been terminated.

The same pattern exists in Drawbridge's TypeScript implementation: `FrequencyTracker` at `clawmoat-drawbridge-sanitizer/src/frequency/index.ts` also deletes terminated sessions on eviction (L285–295). However, Drawbridge's `DrawbridgePipeline` maintains a separate `lastEmittedTier` LRU cache (L85, L727–753 of `pipeline/index.ts`) that remembers tier 3 status independently of the frequency tracker — providing partial mitigation at the pipeline level. Petasos has no equivalent secondary cache.

## Prior Art

Drawbridge mitigates this at the pipeline layer with a `lastEmittedTier` Map that tracks the highest tier ever emitted per session, independent of the frequency tracker's session store. When the frequency state is gone but `lastEmittedTier` shows `tier3`, the pipeline still blocks. This is a defense-in-depth pattern — the frequency tracker itself does not preserve termination across eviction in either codebase.

The OWASP ASI02 category covers session-state manipulation that bypasses tool-use policies. Session eviction as a tier-reset vector is a recognized pattern in agent security literature.

## Remediation

### Approach: Persistent termination set in FrequencyTracker + guard-side query

The fix has two layers, matching the dependency chain from FREQ-02 (PET-30).

### Changes

**1. `petasos/premium/frequency.py` — termination survives eviction (FREQ-02 prerequisite)**

Add a bounded `_terminated_sessions: set[str]` that persists session IDs after tier 3 termination, independent of the main `_sessions` dict. Cap at `max_sessions * 2` with FIFO eviction of the oldest terminated ID (use a `deque` for ordering).

```python
# In __init__:
self._terminated_ids: deque[str] = deque()
self._terminated_set: set[str] = set()
self._max_terminated = config.max_sessions * 2

# In update(), after setting state.terminated = True (L164–165):
if session_id not in self._terminated_set:
    self._terminated_set.add(session_id)
    self._terminated_ids.append(session_id)
    while len(self._terminated_ids) > self._max_terminated:
        evicted = self._terminated_ids.popleft()
        self._terminated_set.discard(evicted)

# In terminate_session():
# Same addition after setting state.terminated = True.
```

Expose via a new method:

```python
def is_terminated(self, session_id: str) -> bool:
    state = self._sessions.get(session_id)
    if state is not None:
        return state.terminated
    return session_id in self._terminated_set
```

`clear()` and `reset()` must also clear the terminated set/deque for the affected session(s).

**2. `petasos/premium/guard.py` — query termination before tier derivation**

In `_derive_tier()` (L170–185), before checking `get_state`, query the persistent termination set:

```python
def _derive_tier(self, session_id: str) -> str:
    # GUARD-01: check persistent termination first
    if self._frequency_tracker.is_terminated(session_id):
        return "tier3"
    state = self._frequency_tracker.get_state(session_id)
    if state is None:
        return "none"
    if state.terminated:
        return "tier3"
    # ... existing threshold logic
```

This ensures that even after LRU eviction, the guard still sees tier 3.

**3. Bounded memory — FIFO cap on terminated set**

The terminated set is capped at `max_sessions * 2` (default: 2000 with the default `max_sessions=1000`). Beyond this, the oldest terminated session ID is evicted from the FIFO. This bounds memory while retaining defense for the realistic attack window. The cap is configurable via a new `max_terminated_sessions` config field (optional; defaults to `max_sessions * 2`).

## Tests Required

| Test | File | Asserts |
|------|------|---------|
| `test_tier3_survives_lru_eviction` | `tests/adversarial/guard/test_tool_smuggling.py` | Session terminated → flood `max_sessions` new sessions → `evaluate()` on original session returns `allowed=False, tier=tier3` |
| `test_tier3_survives_ttl_eviction` | `tests/adversarial/guard/test_tool_smuggling.py` | Session terminated → advance time past TTL → `evaluate()` on original session returns `allowed=False, tier=tier3` |
| `test_is_terminated_after_eviction` | `tests/unit/premium/test_frequency.py` | `is_terminated(sid)` returns `True` after session evicted from `_sessions` |
| `test_terminated_set_fifo_cap` | `tests/unit/premium/test_frequency.py` | After `max_terminated` + 1 terminated sessions, oldest ID is no longer in `is_terminated` |
| `test_reset_clears_terminated` | `tests/unit/premium/test_frequency.py` | `reset(sid)` removes ID from both `_sessions` and `_terminated_set` |
| `test_clear_clears_terminated` | `tests/unit/premium/test_frequency.py` | `clear()` empties `_terminated_set` and `_terminated_ids` |
| `test_derive_tier_uses_is_terminated` | `tests/unit/premium/test_guard.py` | `_derive_tier` returns `"tier3"` when `get_state` returns `None` but `is_terminated` returns `True` |

## Decisions Carried Forward

- **Persistent set, not external store.** A bounded in-memory set is sufficient for the single-process, in-library deployment model. If Petasos ever supports distributed session tracking, this must move to a shared store.
- **FIFO eviction for the terminated set, not LRU.** Terminated sessions are never "accessed" in a way that refreshes recency — FIFO is simpler and correct.
- **Cap at `max_sessions * 2`.** The 2x multiplier gives reasonable retention without unbounded growth. An attacker would need to terminate 2000+ distinct sessions to evict a real terminated ID — far beyond realistic attack windows.
- **Dependency on FREQ-02 (PET-30).** The `is_terminated()` method and the persistent set are the FREQ-02 fix. The guard-side change in `_derive_tier()` is the GUARD-01 fix. Both must land together.
- **`get_state` still returns `None` for evicted sessions.** We do not resurrect full `SessionState` objects from the terminated set — only the boolean termination fact survives. This avoids re-inflating stale scores.

## Done When

- [ ] `FrequencyTracker` gains `_terminated_set`, `_terminated_ids`, and `is_terminated()` method
- [ ] `_evict_one()` and TTL eviction preserve terminated IDs in the set
- [ ] `_derive_tier()` queries `is_terminated()` before `get_state()`
- [ ] FIFO cap on terminated set enforced and tested
- [ ] `reset()` and `clear()` clean up terminated state
- [ ] All 7 tests listed above pass
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of Scope

- Distributed / multi-process session state (Petasos is in-process only)
- Drawbridge backport (Drawbridge has partial mitigation via `lastEmittedTier`; separate ticket if needed)
- Frequency tracker refactoring beyond the terminated set (tracked under FREQ-02 / PET-30)
- Audit trail for eviction events (useful but not blocking for this fix)
