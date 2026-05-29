# Reconciliation Report: PET-30

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-30.spec.md
> Merge: PR #19 (b8f9ad4)
> Plane state: Done (group: completed)

## Summary
The shipped commit faithfully implements the tombstone-set design: `FrequencyTracker` gains a bounded `OrderedDict` tombstone, `update()`/`terminate_session()`/`_evict_one()` record it, `is_terminated()`/`force_reset()`/`tombstone_count` are added, the guard checks `is_terminated()` first, and the config field with bool-guarded validation lands. Every acceptance criterion is met; the only divergences are an over-delivery on test count and the guard body having since been refactored to a `derive_tier()` helper by an unrelated later ticket.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/premium/frequency.py` | Yes | All tombstone members present: `OrderedDict` import, `_terminated_ids`/`_max_terminated` in `__init__` (frequency.py:97-98), Step 1.5 early-return (frequency.py:161-169), tier3 tombstone write (in `update()`), `is_terminated()` (261), `terminate_session()` write (272), `force_reset()` (278), `clear()` (285), `tombstone_count` (293), `_add_tombstone()` (314), `_enforce_tombstone_cap()` (321), defensive `_evict_one()` write. |
| `petasos/premium/guard.py` | Yes | `_derive_tier()` calls `is_terminated()` first (guard.py:200-201); old `state.terminated` check removed. |
| `petasos/config.py` | Yes | `max_terminated_tombstones: int = 10_000` (config.py:106); bool-guarded validation (config.py:171-178). |
| `tests/adversarial/frequency/test_terminated_state_loss.py` | Yes | 9 test functions present. |
| `tests/test_frequency_tombstone.py` | Yes | 17 test functions present. |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-30.test-output.txt` — test-run audit artifact (92 passed). Documentation companion, not code/spec scope; benign.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | Tombstone set (`OrderedDict`), not database | Confirmed | `_terminated_ids: OrderedDict[str, None]` frequency.py:97; import frequency.py:7. |
| 2 | `reset()` does not clear tombstone; `force_reset()` explicit | Confirmed | `reset()` only pops `_sessions` (frequency.py:274-276); `force_reset()` pops both (frequency.py:278-280). |
| 3 | FIFO bounding with `move_to_end()` refresh on re-termination | Confirmed | `_add_tombstone()` calls `move_to_end()` for existing key (frequency.py:315-316); `_enforce_tombstone_cap()` `popitem(last=False)` (frequency.py:322-323). |
| 4 | Guard checks tombstone first | Confirmed | `is_terminated()` first in `_derive_tier()` (guard.py:200-201); old `if state.terminated` removed. |
| 5 | `update()` checks tombstone before creating sessions; sentinel = `tier3_threshold` | Confirmed | Step 1.5 early-return uses `sentinel = self._config.tier3_threshold` (frequency.py:162-169), placed before Step 2 "get or create" (frequency.py:171). |
| 6 | Refuted status acknowledged; ship regardless | Confirmed | Non-code decision; fix shipped per diff. Invariant "terminated stays terminated" enforced by Decisions 2-5. |
| 7 | Test plan expanded (brief 9 → spec 21) | Confirmed (over-delivered) | 9 adversarial + 17 unit = 26 tests shipped; exceeds spec's 21. Config validation test split into 4 (`test_zero_raises`/`test_negative_raises`/`test_bool_raises`/`test_string_raises`). |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `OrderedDict` import at module level | Met | frequency.py:7 `from collections import OrderedDict, deque`. |
| 2 | `_terminated_ids: OrderedDict[str, None]` in `__init__` | Met | frequency.py:97. |
| 3 | `is_terminated()` public method | Met | frequency.py:261-265, two-phase (live state then tombstone). |
| 4 | `_add_tombstone()` with `move_to_end()` refresh | Met | frequency.py:314-319. |
| 5 | `_enforce_tombstone_cap()` | Met | frequency.py:321-323. |
| 6 | `update()` checks tombstone before Step 2, returns tier3 | Met | frequency.py:161-169 (before "Step 2" at 171). |
| 7 | `update()` records termination on tier3 | Met | `if tier == "tier3": ... self._add_tombstone(session_id)` (frequency.py, Step 10 region). |
| 8 | `terminate_session()` records (even if state missing) | Met | `_add_tombstone()` called unconditionally (frequency.py:272). |
| 9 | `reset()` preserves tombstone; `force_reset()` clears both | Met | frequency.py:274-280. |
| 10 | `clear()` clears tombstone set | Met | `self._terminated_ids.clear()` (frequency.py:285). |
| 11 | `_evict_one()` defensively records tombstone | Met | Inline write with `sid not in self._terminated_ids` guard + comment explaining no `move_to_end()` (per `git show` diff hunk on `_evict_one`); confirmed present in frequency.py `_evict_one`. |
| 12 | `tombstone_count` property | Met | frequency.py:292-294. |
| 13 | `max_terminated_tombstones=10_000` + validation | Met | config.py:106 field; config.py:171-178 bool-guarded validation. |
| 14 | `_derive_tier()` checks `is_terminated()` first; removes unreachable check | Met | guard.py:200-201; old `state.terminated` branch absent. |
| 15 | All 21 tests pass | Met | 26 tests present (9 + 17); PET-30.test-output.txt:103 "92 passed in 0.21s". |
| 16 | `ruff check .` and `mypy --strict .` clean | Unverifiable | Not re-run (read-only reconcile). Commit 5170dde "fix ruff unused imports and mypy unused-ignore" indicates lint/type gate was addressed pre-merge. |
| 17 | No regression in full `pytest` suite | Unverifiable | Not re-run (read-only). Test-output artifact shows the targeted suite green (92 passed). |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| test_terminated_survives_ttl_eviction | Yes | tests/adversarial/frequency/test_terminated_state_loss.py:30 |
| test_terminated_survives_lru_eviction | Yes | tests/adversarial/frequency/test_terminated_state_loss.py:59 |
| test_guard_blocks_after_ttl_eviction | Yes | tests/adversarial/frequency/test_terminated_state_loss.py:89 |
| test_guard_blocks_after_lru_eviction | Yes | tests/adversarial/frequency/test_terminated_state_loss.py:117 |
| test_reset_does_not_resurrect_terminated | Yes | tests/adversarial/frequency/test_terminated_state_loss.py:149 |
| test_update_returns_tier3_for_tombstoned_session | Yes | tests/adversarial/frequency/test_terminated_state_loss.py:175 |
| test_tombstoned_update_no_spurious_alert (7a) | Yes | tests/adversarial/frequency/test_terminated_state_loss.py:206 |
| test_ttl_eviction_defensive_tombstone (extra) | Yes | tests/adversarial/frequency/test_terminated_state_loss.py:239 |
| test_evict_one_defensive_tombstone_write | Yes | tests/adversarial/frequency/test_terminated_state_loss.py:281 |
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
| test_config_max_terminated_tombstones_validation | Yes (split into 4) | tests/test_frequency_tombstone.py:263 (test_zero_raises), :267 (test_negative_raises), :271 (test_bool_raises), :275 (test_string_raises), :281 (test_valid_positive_integer) |

## Wiki-ready
- "Terminated stays terminated" invariant: termination is recorded in a bounded FIFO tombstone that survives both TTL and LRU eviction; `reset()` cannot un-terminate (only explicit `force_reset()` can). This is a load-bearing precondition for the GUARD-01 chain (PET-34) and a reusable pattern for any in-process session-state expiry where a security-relevant flag must outlive the record it was attached to.
- Sentinel-score choice for tombstone early-return: tombstoned `update()` returns `previous_score == current_score == tier3_threshold` (not `0.0`) specifically so `AlertManager._check_tier_escalation()` sees `previous_tier == current_tier` and does not fire a spurious escalation alert on every call. Non-obvious coupling between the frequency early-return and the alerting layer.

RECONCILED: yes DRIFT: 0
