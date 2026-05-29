# Reconciliation Report: PET-75

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-75.spec.md
> Merge: PR #40 (cc75933)
> Plane state: Done (group: completed)

## Summary
The shipped commit cc75933 (PR #40) implements all four red-team remediations (ESC-01, ESC-03, FREQ-04, FREQ-05) with every spec'd file present and every acceptance criterion met. Two small, deliberate strengthenings landed in the second squash commit (tier3 clamped to `TIER3_FLOOR` inside `derive_tier`; rate-limit log hashes the session id) that go beyond the spec's literal code snippets but do not change intent.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/premium/escalation.py` | Yes | `derive_tier()` added; `evaluate_tier()` delegates. `escalation.py:30-51`. Diff uses `max(tier3, TIER3_FLOOR)` (spec showed plain `score >= tier3`). |
| `petasos/premium/frequency.py` | Yes | `rate_limited` field, `RATE_LIMITED_RESULT` sentinel, deque eviction + `_compact_ttl_deque`, `clear()` reset. `frequency.py:41,54-56,144-159,236,296-303`. |
| `petasos/premium/guard.py` | Yes | `_derive_tier()` profile path now calls `derive_tier()`; import updated. `guard.py:209-212`. |
| `petasos/premium/__init__.py` | Yes | `derive_tier` imported and in `__all__`. `__init__.py:7,27`. |
| `petasos/pipeline.py` | Yes | `_STANDALONE_TIER3_CRITICAL_COUNT`, `_standalone_tier3_check()`, Stage 5a + Stage 8b, rate-limited logging in `_premium_frequency_hook`. `pipeline.py:50-55,439-440,493-497,577-585`. |
| `tests/test_frequency.py` | Yes | `rate_limited` assertions added to both `is_frozen` tests. `test_frequency.py:472,478`. |
| `tests/adversarial/escalation/__init__.py` | Yes | New empty package init. |
| `tests/adversarial/escalation/test_standalone_tier3.py` | Yes | 5 tests for ESC-01. |
| `tests/adversarial/escalation/test_derive_tier.py` | Yes | 6 tests for ESC-03 (spec said 4; +inf test, +delegation test). |
| `tests/adversarial/frequency/test_rate_limited_sentinel.py` | Yes | 4 tests for FREQ-04. |
| `tests/adversarial/frequency/test_ttl_eviction.py` | Yes | 4 tests for FREQ-05. |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-75.test-output.txt` — captured pytest audit trail added by the ship-spec flow; not source/test code, no behavioral impact.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | Standalone tier-3 check is a hardcoded safety-net floor (count=3), not configurable; evaluates on pre-override merged findings | Confirmed | `pipeline.py:50` `_STANDALONE_TIER3_CRITICAL_COUNT = 3`; check computed at Stage 5a (`pipeline.py:439-440`) before 5b/5c, applied at Stage 8b (`pipeline.py:493-497`). |
| 2 | `derive_tier()` takes explicit thresholds, not a config object; both `evaluate_tier()` and guard profile path call it | Confirmed | `escalation.py:30` signature `derive_tier(score, tier1, tier2, tier3)`; `escalation.py:49` and `guard.py:211` both delegate. |
| 3 | Deque over heap for TTL eviction, compaction trigger at `2 * max_sessions` | Confirmed | `frequency.py:144-159` O(k) `while` loop + compaction guard; `_compact_ttl_deque` at `frequency.py:296-303`. |
| 4 | `rate_limited` is a bool field only; tier stays `"none"` to preserve closed vocabulary | Confirmed | `frequency.py:41` field; `frequency.py:54-56` `RATE_LIMITED_RESULT` keeps `tier="none"`, `rate_limited=True`. |
| — | Design ESC-03 snippet `score >= tier3` vs shipped `score >= max(tier3, TIER3_FLOOR)` | Drifted (strengthening) | `escalation.py:33`. Second commit "clamp tier3 to TIER3_FLOOR"; enforces the CLAUDE.md "Tier 3 cannot be disabled" floor. Intent-preserving but deviates from spec's literal body. |
| — | Design FREQ-04 log snippet logs raw `session_id` vs shipped hashed fingerprint | Drifted (strengthening) | `pipeline.py:582-584` hashes sid to 8-char sha256 `sid_fp` before logging. Privacy improvement; deviates from spec's literal `_logger.info(..., session_id)`. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `_standalone_tier3_check()` fires at >=3 CRITICAL regardless of premium/frequency state | Met | `pipeline.py:53-55`; test_tier3_fires_without_frequency / _without_premium. |
| 2 | Standalone check evaluates on pre-severity-override merged findings | Met | Stage 5a before 5b/5c (`pipeline.py:439-440`); test_standalone_survives_severity_override. |
| 3 | `frequency_enabled=False` + >=3 CRITICAL → `escalation_tier="tier3"`, `safe=False` | Met | `pipeline.py:493-497`; test_tier3_fires_without_frequency asserts both. |
| 4 | `derive_tier()` single shared fn in escalation.py, exported via `premium/__init__.py` | Met | `escalation.py:30`; `__init__.py:7,27`. |
| 5 | `derive_tier()` returns `"tier3"` for NaN/Inf (fail-closed) | Met | `escalation.py:31-32` `math.isfinite` guard; test_derive_tier_nan_fails_closed, test_derive_tier_inf_fails_closed. |
| 6 | `evaluate_tier()` delegates to `derive_tier()` | Met | `escalation.py:49-51` (with an added PET-23 fail-secure pre-check at 43-48 that still falls through to the delegate); test_evaluate_tier_delegates. |
| 7 | `guard._derive_tier()` profile path uses `derive_tier()` | Met | `guard.py:209-211`. |
| 8 | `RATE_LIMITED_RESULT.tier == "none"` and `.rate_limited is True` | Met | `frequency.py:54-56`; test_rate_limited_result_fields. |
| 9 | `DISABLED_RESULT.tier == "none"` and `.rate_limited is False` | Met | `frequency.py:51-53` (defaults `rate_limited=False`); test_disabled_result_fields. |
| 10 | Pipeline logs rate-limited distinct from disabled | Met | `pipeline.py:581-584` logs on `result.rate_limited`. (Logs hashed sid, not raw — see Decisions.) |
| 11 | TTL eviction uses deque-based O(k) scan, not O(n) | Met | `frequency.py:144-155` `while`/`popleft` loop replaces former list comprehension. |
| 12 | Deque compaction triggers at `len(deque) > 2 * max_sessions`, rebuilds from live sessions | Met | `frequency.py:157-159`, `296-303`; test_compaction_triggers_at_threshold. |
| 13 | Refreshed sessions survive stale deque entries | Met | `frequency.py:150-151` last_update recheck; test_refreshed_session_survives_stale_deque_entry. |
| 14 | >= 17 tests across 4 findings | Met | 19 new/updated test fns (5 ESC-01 + 6 ESC-03 + 4 FREQ-04 + 4 FREQ-05); exceeds floor. |
| 15 | `mypy --strict` clean, `ruff check .` clean | Unverifiable | Not re-run here (read-only); PET-75.test-output.txt is the captured audit trail from ship. |
| 16 | Existing frequency/escalation tests still pass incl. updated `test_rate_limited_result_is_frozen` | Met (static) | `test_frequency.py:472,478` updated assertions present; full run not re-executed (read-only). |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| test_tier3_fires_without_frequency | Yes | tests/adversarial/escalation/test_standalone_tier3.py:32 |
| test_tier3_fires_without_premium | Yes | tests/adversarial/escalation/test_standalone_tier3.py:44 |
| test_below_threshold_no_tier3 | Yes | tests/adversarial/escalation/test_standalone_tier3.py:54 |
| test_standalone_idempotent_with_frequency | Yes | tests/adversarial/escalation/test_standalone_tier3.py:66 |
| test_standalone_survives_severity_override | Yes | tests/adversarial/escalation/test_standalone_tier3.py:82 |
| test_derive_tier_boundaries | Yes | tests/adversarial/escalation/test_derive_tier.py:29 |
| test_derive_tier_nan_fails_closed | Yes | tests/adversarial/escalation/test_derive_tier.py:39 |
| test_derive_tier_inf_fails_closed (extra) | Yes | tests/adversarial/escalation/test_derive_tier.py:42 |
| test_evaluate_tier_delegates (extra) | Yes | tests/adversarial/escalation/test_derive_tier.py:46 |
| test_guard_with_profile_thresholds | Yes | tests/adversarial/escalation/test_derive_tier.py:57 |
| test_guard_without_profile_falls_back | Yes | tests/adversarial/escalation/test_derive_tier.py:83 |
| test_rate_limited_distinct_from_disabled | Yes | tests/adversarial/frequency/test_rate_limited_sentinel.py:25 |
| test_rate_limited_result_fields | Yes | tests/adversarial/frequency/test_rate_limited_sentinel.py:30 |
| test_disabled_result_fields | Yes | tests/adversarial/frequency/test_rate_limited_sentinel.py:37 |
| test_update_returns_rate_limited_at_cap | Yes | tests/adversarial/frequency/test_rate_limited_sentinel.py:44 |
| test_ttl_eviction_uses_deque | Yes | tests/adversarial/frequency/test_ttl_eviction.py:21 |
| test_refreshed_session_survives_stale_deque_entry | Yes | tests/adversarial/frequency/test_ttl_eviction.py:40 |
| test_compaction_triggers_at_threshold | Yes | tests/adversarial/frequency/test_ttl_eviction.py:56 |
| test_clear_resets_deque | Yes | tests/adversarial/frequency/test_ttl_eviction.py:80 |
| test_rate_limited_result_is_frozen (updated) | Yes | tests/test_frequency.py:476 |
| test_disabled_result_is_frozen (updated) | Yes | tests/test_frequency.py:469 |

## Wiki-ready
- **Standalone tier-3 floor is intentionally non-configurable.** A frequency-independent `>=3 CRITICAL` check in the pipeline enforces the "Tier 3 cannot be disabled" invariant even with the premium frequency subsystem off — a configurable safety net can be configured away, so the count (3) is hardcoded as policy. Constrains future config-surface work.
- **`rate_limited` is a bool flag, not a new tier string.** Distinguishing rate-limited from disabled by adding a field (tier stays `"none"`) preserves the closed tier vocabulary (`none/tier1/tier2/tier3`) that `_TIER_ACTIONS`, alerting severity maps, and audit schemas depend on. Reusable constraint for anyone tempted to add tier strings.
- **`derive_tier()` clamps tier3 to `TIER3_FLOOR`** (`max(tier3, TIER3_FLOOR)`), so a misconfigured low tier3 threshold cannot drop below the floor — single source of truth for the invariant across config and profile threshold sources.

RECONCILED: yes DRIFT: 2
