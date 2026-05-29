# Reconciliation Report: PET-17

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-17.spec.md
> Merge: PR #17 (merge 93e2da2; fix 5b7ff30 + style 55be0bb)
> Plane state: Done (group: completed)

## Summary
PET-17 (ALRT-02 per-session alert contribution caps) shipped exactly as specified: both config fields with validation and cross-field check, the additive `_per_session_minute_timestamps` gate inserted between cooldown and the global per-minute cap, reject-don't-evict memory bound, `_prune_stale` cleanup, and the `session_rate_limited_count` property are all present in current master code. All 12 new alerting tests, 7 config tests, and both required existing-test adjustments are present.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/config.py` | Yes | +25 lines: two fields (config.py:85-86) + three validation blocks (config.py:312-334) |
| `petasos/premium/alerting.py` | Yes | +35 lines (then -3 net by ruff format 55be0bb): tracking dict, counter, property, gate, prune block |
| `tests/test_alerting.py` | Yes | +265 lines: 12 new tests + adjustments to existing tests |
| `tests/test_config.py` | Yes | +32 lines: 7 new config validation tests |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-17.test-output.txt` (+87) — routine pytest-output companion artifact captured by the ship workflow; not source/behavior, no drift impact.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | Additive layer, not replacement — session gate between cooldown and global per-minute cap; global cap remains hard ceiling | Confirmed | alerting.py:126-128 cooldown check → 130-145 session gate → 147-151 global per-minute cap. Order matches spec. |
| D2 | Default contribution cap of 2 | Confirmed | config.py:85 `alert_per_session_contribution_cap: int = 2`. Re-entry suppression with cap=1 covered by `test_cap_1_suppresses_reentry` (test_alerting.py:825). |
| D3 | Memory bound mandatory — reject (rate-limit) new sessions, don't evict; promoted to config field | Confirmed | config.py:86 `alert_max_session_contribution_entries: int = 10_000`; alerting.py:131-137 rejects new key when dict at capacity (increments `_session_rate_limited_count`, no eviction). |
| D4 | Critical alerts unaffected; session gate only on non-critical path | Confirmed | alerting.py:110-120 critical branch has no session gate; gate lives in `else` (non-critical) branch at 130-145. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `PetasosConfig` has `alert_per_session_contribution_cap: int = 2` with validation | Met | config.py:85; validation 312-320 (int / not-bool / >0) |
| 2 | `PetasosConfig` has `alert_max_session_contribution_entries: int = 10_000` with validation | Met | config.py:86; validation 321-329 |
| 3 | Cross-field validation cap <= per_minute_cap (reject `>`, allow `==`) | Met | config.py:330-334 uses `>` operator |
| 4 | `AlertManager` tracks per-(rule_id, session_id) counts in `_per_session_minute_timestamps` | Met | alerting.py:48 init; key `(candidate.rule_id, session_id)` at 130 |
| 5 | Exposes `session_rate_limited_count` property | Met | alerting.py:52 counter, 72-74 property |
| 6 | Non-critical path checks memory bound, then session cap, before global per-minute cap | Met | alerting.py:131-137 (memory bound) → 139-145 (session cap) → 147-151 (global) |
| 7 | Memory bound rejects new sessions rather than evicting live entries | Met | alerting.py:131-137 `continue` on capacity; no eviction code |
| 8 | Session gate does not consume global cap slots when rate-limiting | Met | alerting.py:136-137 and 144-145 `continue` before global deque appends at 160-161 |
| 9 | `_prune_stale` cleans session contribution deques (60s window) | Met | alerting.py:407-413 evicts 60s, deletes empty deques |
| 10 | `rate_limited_count` semantics unchanged (global-only); `session_rate_limited_count` session-only | Met | session gates increment `_session_rate_limited_count` only (136, 144); global caps increment `_rate_limited_count` (118, 150, 156) |
| 11 | All 12 new alerting tests pass | Met (present) | test_alerting.py:673,693,715,742,767,787,808,825,847,879,898,903 — all 12 defined |
| 12 | 7 new config validation tests pass | Met (present) | test_config.py:127,131,135,139,143,147,151 — all 7 defined |
| 13 | Existing tests adjusted: `test_tier3_bypasses_per_minute_cap` and `test_rate_limited_count_reflects_caps` pass `alert_per_session_contribution_cap=1` | Met | test_alerting.py:431 and 655-656 |
| 14 | Critical exemption tests pass without regression | Unverifiable | `test_tier3_bypasses_per_minute_cap` adjusted and present (test_alerting.py:430); full suite not run in this read-only pass |
| 15 | `ruff check .` and `mypy --strict .` clean | Unverifiable | Not executed in read-only reconciliation; style commit 55be0bb shows ruff format was applied |
| 16 | No regression in full `pytest` suite | Unverifiable | Test artifact `PET-17.test-output.txt` shipped in diff but suite not re-run here |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| test_session_contribution_cap_limits_single_session | Yes | tests/test_alerting.py:673 |
| test_throwaway_sessions_cannot_exhaust_rule_cap | Yes | tests/test_alerting.py:693 |
| test_session_contribution_independent_across_rules | Yes | tests/test_alerting.py:715 |
| test_session_contribution_window_resets | Yes | tests/test_alerting.py:742 |
| test_session_none_uses_none_key | Yes | tests/test_alerting.py:767 |
| test_per_session_deque_pruned | Yes | tests/test_alerting.py:787 |
| test_memory_bound_rejects_new_sessions | Yes | tests/test_alerting.py:808 |
| test_cap_1_suppresses_reentry | Yes | tests/test_alerting.py:825 |
| test_three_gate_composition | Yes | tests/test_alerting.py:847 |
| test_session_rate_limited_count_separate | Yes | tests/test_alerting.py:879 |
| test_cross_field_validation_cap_gt_per_minute (alerting) | Yes | tests/test_alerting.py:898 |
| test_memory_bound_recovery_after_expiry | Yes | tests/test_alerting.py:903 |
| test_alert_per_session_contribution_cap_rejects_zero | Yes | tests/test_config.py:127 |
| test_alert_per_session_contribution_cap_rejects_negative | Yes | tests/test_config.py:131 |
| test_alert_per_session_contribution_cap_rejects_bool | Yes | tests/test_config.py:135 |
| test_alert_max_session_contribution_entries_rejects_zero | Yes | tests/test_config.py:139 |
| test_alert_max_session_contribution_entries_rejects_negative | Yes | tests/test_config.py:143 |
| test_alert_max_session_contribution_entries_rejects_bool | Yes | tests/test_config.py:147 |
| test_cross_field_validation_cap_gt_per_minute (config) | Yes | tests/test_config.py:151 |
| test_per_minute_cap (verify unchanged) | Yes | tests/test_alerting.py:361 |
| test_per_hour_cap (verify unchanged) | Yes | tests/test_alerting.py:376 |
| test_100_rapid_triggers_bounded (verify unchanged) | Yes | tests/test_alerting.py:392 |

## Wiki-ready
- Reject-don't-evict memory bound (D3): when the per-session tracking dict is full, new session keys are rate-limited rather than evicting live entries — eviction would let an attacker reset legitimate sessions' contribution counts and defeat the protection. Reusable pattern for any per-key tracking structure that is itself an attack surface.
- Cap-of-2 default (D2): a per-session cap of 1 would suppress a legitimate decay/re-cross re-entry alert within the same minute; cap=2 bounds throwaway-session attacks to ceil(per_minute_cap/2) while preserving re-entry alerts. Non-obvious tuning rationale tied to frequency-decay behavior.

RECONCILED: yes DRIFT: 1
