# Reconciliation Report: PET-34

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-34.spec.md
> Merge: #25 (685cd40)
> Plane state: Done (group: completed)

## Summary

PET-34 (GUARD-01) is the TTL-eviction hardening (Decision D7) of the termination-tombstone defense; the bulk of the infrastructure (D1-D6, D8) shipped earlier under PET-30/FREQ-02 (#19, b8f9ad4) as the spec's "Relationship to PET-30" section states. The PET-34 commit (#25) adds exactly the defensive tombstone write in the TTL eviction loop plus its adversarial test; current code on master matches the spec's intent with no drift.

## Scope

| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/premium/frequency.py` | Yes (#25) | #25 adds only the TTL-eviction defensive write (lines 152-154). The `_terminated_ids`/`is_terminated()`/`_add_tombstone()`/`_enforce_tombstone_cap()`/`_evict_one()` write/`update()` early-return infra landed in PET-30 (#19); spec scope row attributes the full set to PET-34, but D7 + "Relationship to PET-30" make this split explicit. Present on disk. |
| `petasos/premium/guard.py` | No (in #19) | `_derive_tier()` `is_terminated()`-before-`get_state()` check shipped under PET-30. Present on disk at guard.py:200. Not in the #25 diff (correct per spec D7 scoping). |
| `petasos/config.py` | No (in #19) | `max_terminated_tombstones` field + validation shipped under PET-30. Present on disk at config.py:106,172-178. Not in #25 diff. |
| `tests/test_frequency_tombstone.py` | No (in #19) | 17 unit test functions shipped under PET-30. Present on disk. Not in #25 diff. |
| `tests/adversarial/frequency/test_terminated_state_loss.py` | Yes (#25) | #25 adds test 8 (`test_ttl_eviction_defensive_tombstone`); the other 8 adversarial tests shipped under PET-30. Present on disk. |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-34.test-output.txt` — test-run audit artifact added by the ship workflow; not code, not a spec-scope concern.

## Decisions

| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | OrderedDict, not set+deque | Confirmed | `frequency.py:97` `_terminated_ids: OrderedDict[str, None]`; `move_to_end` at `:316`; `popitem(last=False)` at `:323` |
| D2 | Tombstone, not full state resurrection | Confirmed | `is_terminated()` (`:261-265`) returns bool only; `get_state()` (`:249-259`) still returns `None` for evicted sessions |
| D3 | reset() preserves tombstones, force_reset() clears | Confirmed | `reset()` pops only `_sessions` (`:274-276`); `force_reset()` pops both `_sessions` and `_terminated_ids` (`:278-280`) |
| D4 | Defensive tombstone write in `_evict_one()` (direct insert, no move_to_end) | Confirmed | `_evict_one()` `:344-346` direct `self._terminated_ids[sid] = None` + `_enforce_tombstone_cap()`; comment `:341-343` explains avoidance of `move_to_end` |
| D5 | Tombstone early-return in update() with sentinel score | Confirmed | `update()` Step 1.5 `:162-169` returns tier3/terminated with `previous_score == current_score == tier3_threshold` |
| D6 | Cap at `max_terminated_tombstones` (default 10,000) | Confirmed | `config.py:106` `max_terminated_tombstones: int = 10_000`; `frequency.py:98` reads it into `_max_terminated` |
| D7 | Defensive tombstone write in TTL eviction (THIS ticket) | Confirmed | `frequency.py:152-154` checks `state_ev.terminated and sid not in self._terminated_ids` before `del`, writes tombstone + enforces cap. This is the #25 diff. |
| D8 | `is_terminated()` is intentionally token-free | Confirmed | `is_terminated(self, session_id: str)` (`:261`) takes a bare str, does not route through `_resolve_session_id`; guard calls it with raw `session_id` (`guard.py:200`) |

## Acceptance Criteria

Note: the spec's "Done when" checkboxes were authored pre-implementation; D7 items show unchecked but are the deliverables of #25 and are present in shipped code. Reconciled against shipped code, not checkbox state.

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `FrequencyTracker` has `_terminated_ids: OrderedDict` and `is_terminated()` | Met | `frequency.py:97`, `:261-265` |
| 2 | `_evict_one()` preserves terminated IDs via defensive tombstone write | Met | `frequency.py:344-347` |
| 3 | TTL eviction writes defensive tombstone for terminated sessions (D7) | Met | `frequency.py:152-154` (the #25 change) |
| 4 | `_derive_tier()` queries `is_terminated()` before `get_state()` | Met | `guard.py:200-206` (`is_terminated` at :200, `get_state` at :204/:206) |
| 5 | FIFO cap on terminated set enforced and tested | Met | `_enforce_tombstone_cap()` `frequency.py:321-323`; tests `test_tombstone_bounded_fifo`, `test_tombstone_cap_at_one` in test_frequency_tombstone.py |
| 6 | `reset()` preserves and `force_reset()` clears terminated state | Met | `frequency.py:274-280`; tests `test_reset_preserves_tombstone`, `test_force_reset_clears_tombstone` |
| 7 | `clear()` clears terminated state | Met | `frequency.py:282-286` clears `_terminated_ids`; test `test_clear_clears_tombstones` |
| 8 | Test 8 (TTL defensive tombstone) passes | Met | `test_ttl_eviction_defensive_tombstone` at test_terminated_state_loss.py:239; PET-34.test-output.txt shows PASSED, 68 passed |
| 9 | All other tests pass (17 unit + 9 adversarial = 26) | Met | PET-34.test-output.txt: 17 in test_frequency_tombstone.py (config split into 5 funcs) + 9 in test_terminated_state_loss.py all PASSED; 68 passed total |
| 10 | `ruff check .` and `mypy --strict .` clean | Unverifiable | No lint/type output captured in commit; not re-run here (read-only reconcile). Code type-annotated; no evidence of failure. |
| 11 | No regression in `pytest` full suite | Unverifiable | Commit captures only the targeted 68-test run, not the full suite; not re-run here. |

## Test Plan

| Test | Exists? | Location |
|---|---|---|
| test_terminate_session_sets_tombstone | Yes | tests/test_frequency_tombstone.py:28 |
| test_terminate_session_tombstone_when_state_missing | Yes | tests/test_frequency_tombstone.py:46 |
| test_tier3_update_sets_tombstone | Yes | tests/test_frequency_tombstone.py:62 |
| test_reset_preserves_tombstone | Yes | tests/test_frequency_tombstone.py:82 |
| test_force_reset_clears_tombstone | Yes | tests/test_frequency_tombstone.py:103 |
| test_tombstone_bounded_fifo | Yes | tests/test_frequency_tombstone.py:125 |
| test_tombstone_cap_at_one | Yes | tests/test_frequency_tombstone.py:148 |
| test_clear_clears_tombstones | Yes | tests/test_frequency_tombstone.py:166 |
| test_is_terminated_false_for_unknown | Yes | tests/test_frequency_tombstone.py:186 |
| test_is_terminated_true_for_live_terminated | Yes | tests/test_frequency_tombstone.py:199 |
| test_tombstone_count_property | Yes | tests/test_frequency_tombstone.py:221 |
| test_double_termination_idempotent | Yes | tests/test_frequency_tombstone.py:240 |
| test_config_max_terminated_tombstones_validation (5 sub-funcs) | Yes | tests/test_frequency_tombstone.py:263-281 (test_zero/negative/bool/string_raises, test_valid_positive_integer) |
| test_terminated_survives_ttl_eviction | Yes | tests/adversarial/frequency/test_terminated_state_loss.py:30 |
| test_terminated_survives_lru_eviction | Yes | tests/adversarial/frequency/test_terminated_state_loss.py:59 |
| test_guard_blocks_after_ttl_eviction | Yes | tests/adversarial/frequency/test_terminated_state_loss.py:89 |
| test_guard_blocks_after_lru_eviction | Yes | tests/adversarial/frequency/test_terminated_state_loss.py:117 |
| test_reset_does_not_resurrect_terminated | Yes | tests/adversarial/frequency/test_terminated_state_loss.py:149 |
| test_update_returns_tier3_for_tombstoned_session | Yes | tests/adversarial/frequency/test_terminated_state_loss.py:175 |
| test_tombstoned_update_no_spurious_alert | Yes | tests/adversarial/frequency/test_terminated_state_loss.py:206 |
| test_ttl_eviction_defensive_tombstone (NEW, D7, #25) | Yes | tests/adversarial/frequency/test_terminated_state_loss.py:239 |
| test_evict_one_defensive_tombstone_write | Yes | tests/adversarial/frequency/test_terminated_state_loss.py:281 |

## Wiki-ready

- D3 (reset() preserves tombstones; force_reset() is the only clear path) — non-obvious and constraining: it deliberately departs from the brief because letting `reset()` clear termination would reopen the exact bypass the ticket closes. Reusable invariant for any future session-rehabilitation API.
- D7 (TTL-eviction defensive tombstone) — the subtle FIFO-evict-then-TTL-expire ordering bug: a tombstone can be FIFO-evicted while its session is still live in `_sessions`, so every eviction path that deletes a `terminated=True` session must re-write a defensive tombstone. Constraining design rule for the tombstone subsystem.
- D4/D7 shared rule: defensive tombstone writes use direct `_terminated_ids[sid] = None` (never `_add_tombstone()`/`move_to_end()`) so eviction does not refresh FIFO age. Easy to get wrong on future edits.

RECONCILED: yes DRIFT: 0
