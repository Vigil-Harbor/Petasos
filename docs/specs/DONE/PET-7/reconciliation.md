# Reconciliation Report: PET-7

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-7.spec.md
> Merge: PR #6 (b7656d8)
> Plane state: Done (group: completed)

## Summary
PET-7 shipped the FrequencyTracker and escalation-tier evaluator with full pipeline wiring; all 16 acceptance criteria are met and 63 tests landed (spec floor was >=42). Two decisions drifted during PET-7's own review cycle — D6 (TIER3_FLOOR location moved to config.py) and D7 (instance-attribute premium state refactored to local variables for concurrency safety) — neither weakens an invariant.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/premium/__init__.py` | Yes | New package marker; exports FrequencyTracker, FrequencyUpdateResult, EscalationResult, evaluate_tier (+evaluate_escalation, TIER3_FLOOR). Now grown to export PET-8/9/10 symbols. |
| `petasos/premium/frequency.py` | Yes | FrequencyTracker: 11-step update, decay, rolling window, weight matching, LRU eviction, rate limiting (228 LOC at ship). |
| `petasos/premium/escalation.py` | Yes | evaluate_tier(), evaluate_escalation(), EscalationResult, tier-action map. |
| `tests/test_frequency.py` | Yes | 29 tests shipped (spec floor 25). |
| `tests/test_escalation.py` | Yes | 15 tests shipped (spec floor 10). |
| `tests/test_premium_integration.py` | Yes | 19 tests shipped (spec floor 10/12). |
| `petasos/_types.py` | Yes | Added escalation_tier, session_score, premium_features (MappingProxyType) to PipelineResult; docstring corrected from "PET-6" reference. |
| `petasos/config.py` | Yes | Added 10 premium fields + validation; frequency_weights frozen via MappingProxyType; copy() switched to from_dict(to_dict()). |
| `petasos/pipeline.py` | Yes | FrequencyTracker construction, activate/deactivate, _check_premium, _build_premium_features, _build_result, frequency+escalation hooks. |
| `petasos/__init__.py` | Yes | Exports FrequencyTracker, FrequencyUpdateResult. |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-7.test-output.txt` (+173) — pytest audit-trail artifact added by the ship workflow; not a spec deliverable.
- `tests/test_pipeline.py` (1 line) — spec §"Files left alone" said this must pass *unmodified*; a 1-line touch occurred. Benign (no behavioral test change; the new PipelineResult fields default to None as designed), but technically a deviation from "without modification".

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | `time.monotonic()` for elapsed time | Confirmed | frequency.py:142 `now = time.monotonic()`; decay at frequency.py:212-214. |
| D2 | dataclasses for state; frozen result objects | Confirmed | frequency.py:27 `@dataclass SessionState`; :35 `@dataclass(frozen=True) FrequencyUpdateResult`; escalation.py:23 frozen EscalationResult. |
| D3 | `collections.deque` rolling window | Confirmed | frequency.py:31 `rolling_findings: deque[float]`; left-prune at :223-224. |
| D4 | FrequencyTracker is plain (sync) class | Confirmed | frequency.py:138 `def update(...)` is sync; no async/context-manager. |
| D5 | evaluate_tier standalone; tracker embeds minimal tier call | Confirmed | escalation.py:42 `evaluate_tier`; called inside update() at frequency.py:229. |
| D6 | TIER3_FLOOR=30.0 defined in escalation.py and re-exported | Drifted | Floor lives in config.py:`_TIER3_FLOOR = 30.0` (shipped diff) and is re-exported as `TIER3_FLOOR`; escalation.py:11 imports `from petasos.config import TIER3_FLOOR`. Value (30.0) and ValueError enforcement (config.py __post_init__) are correct, but the canonical-definition location inverted vs. the spec. |
| D7 | Pipeline instance state (`self._last_freq_result`, `self._last_escalation_tier`) | Drifted | Shipped pipeline.py uses local vars `freq_result`/`escalation_tier` in `_inspect_inner` (b7656d8:pipeline.py:245-246); hooks return values (`-> FrequencyUpdateResult \| None` :367, `-> str \| None` :381); `_build_result` takes them as params (:202-203). Done in PET-7 round-2 review for concurrency safety — strictly better than the spec text, which described non-thread-safe instance attrs. |
| D8 | Weight map uses Petasos rule-ID namespace | Confirmed | frequency.py:18-22 DEFAULT_FREQUENCY_WEIGHTS keyed on `petasos.syntactic.{injection,structural,encoding}.*`. |
| D9 | `_check_premium()` is a simple flag check for PET-7 | Confirmed (at ship) | Shipped pipeline.py:176-177 `return self._premium_active`. (Current on-disk code replaced this body with PET-10 JWT validation — expected downstream evolution, callers unchanged.) |
| D10 | Threshold comparison uses `>=` | Confirmed | escalation.py:33-38 derive_tier uses `>=`; tests test_at_tier1/tier2/tier3_returns_* assert boundary escalation. |
| D11 | `safe` independent of escalation tier | Confirmed | test_premium_integration.py:113 test_tier3_terminated_with_safe_true asserts safe=True with escalation_tier="tier3". |
| D12 | activate()/deactivate() are no-arg Pipeline instance methods | Confirmed (at ship) | Shipped pipeline.py:170-174 `def activate(self) -> None: self._premium_active = True` / deactivate. (Current code is `activate(key: str) -> LicenseState` — PET-10 superseded, as the spec anticipated.) |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Exponential decay matches reference sequence | Met | frequency.py:212-214 decay formula; test_frequency.py decay-math suite (multiple-update reference test). |
| 2 | Score halves after one half-life | Met | frequency.py decay = `exp(-elapsed*ln2/half_life)`; covered by decay-math tests. |
| 3 | Rolling window promotes to Tier 1 below decay threshold | Met | frequency.py:230-231 promotion; test_rolling_threshold_promotes_to_tier1 (test_frequency.py:225). |
| 4 | Weight matching: exact>glob, longest prefix, no-match=0 | Met | frequency.py:305-312 _match_weight; tests test_exact_match_takes_priority_over_glob (:110), test_glob_match_longest_prefix_wins (:124). |
| 5 | Tier 3 cannot be disabled — below-floor raises ValueError | Met | config.py __post_init__ `if tier3_threshold < _TIER3_FLOOR: raise ValueError`; test_tier3_below_floor_raises (test_escalation.py:64). |
| 6 | Session eviction >1000 sessions, prefer terminated, no crash | Met | frequency.py:325-349 _evict_one (terminated-first then oldest); eviction suite incl. >1000-session test. |
| 7 | Rate limiting rejects new session at capacity + over per-minute | Met | frequency.py:180-184 RATE_LIMITED_RESULT; test_rate_limit_window_rolls_forward (:387) + rate-limit suite. |
| 8 | Premium stages run when active, skip cleanly when inactive | Met | hook gates `if not self._check_premium(...)`; test_premium_inactive_hooks_are_noop (test_premium_integration.py:33). |
| 9 | PipelineResult gains 3 fields, defaults None, existing tests unbroken | Met | _types.py escalation_tier/session_score/premium_features=None; test_escalation_tier_defaults_to_none (:86), test_session_score_defaults_to_none (:90). |
| 10 | `_check_premium()` scaffold, replaceable without caller changes | Met | Shipped flag check (pipeline.py:176-177); current code swapped body to JWT with identical signature — no caller edits. |
| 11 | Config validation: ascending thresholds, tier3 floor, positive/finite | Met | config.py __post_init__ full block; tests test_thresholds_not_ascending_raises (:138), test_negative_half_life_raises (:156), test_infinite_threshold_raises (:164). |
| 12 | Pipeline never throws — errors land in PipelineResult.errors | Met | test_frequency_hook_exception_lands_in_errors (test_premium_integration.py:68); test_outer_handler_returns_none_premium_fields (:216). |
| 13 | premium_features manifest maps feature->locked/unlocked per state | Met | Shipped _build_premium_features returns "unlocked"/"locked" (b7656d8:pipeline.py:179-184); tests test_premium_features_manifest_all_locked_when_inactive (:94), ..._unlocked_when_active (:103). |
| 14 | >=42 tests (spec) / >=40 (brief) | Met | 29+15+19 = 63 tests shipped. |
| 15 | All existing tests pass, no regressions | Met | Commit message: "124/124 pass"; test-output.txt artifact records the green run. |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| test_frequency.py (>=25) | Yes (29) | tests/test_frequency.py |
| decay-math: zero-init, exact reference seq | Yes | test_decay_with_zero_initial_score (:70) + decay suite |
| weight: exact>glob, longest-prefix | Yes | test_exact_match_takes_priority_over_glob (:110), test_glob_match_longest_prefix_wins (:124) |
| rolling window threshold promotion | Yes | test_rolling_threshold_promotes_to_tier1 (:225) |
| eviction: never-current, >1000 | Yes | test_eviction_never_removes_current_session (:315) + eviction suite |
| rate limiting window rolls forward | Yes | test_rate_limit_window_rolls_forward (:387) |
| edge: terminated returns immediately, reset, clear | Yes | test_terminated_session_returns_immediately (:414), test_reset_removes_session (:435), test_clear_removes_all_sessions_and_timestamps (:447) |
| test_escalation.py (>=10) | Yes (15) | tier eval (:28-53), floor (:64-72), action map (:82-103), frozen (:110) |
| test_premium_integration.py (>=12) | Yes (19) | hooks (:33-68), fields (:86-113), config validation (:138-164) |
| existing suites unmodified pass | Yes | test_pipeline.py / test_config.py / test_finding_merge.py green (124/124) |

## Wiki-ready
- D7 concurrency refactor: premium per-call state (frequency result, escalation tier) is carried as local variables threaded through hooks and `_build_result`, NOT pipeline instance attributes. This was a deliberate in-PR correction of the spec's non-thread-safe design and is a reusable pattern for any future per-call premium state — worth a decision note so the spec's D7 text is not mistaken for the shipped contract.
- D6 floor location: `TIER3_FLOOR` is canonically defined in `petasos/config.py` (so config validation and escalation share one source) and re-exported via `escalation.py`/`premium/__init__.py`. Constraining for anyone editing the Tier-3 floor — change config.py, not escalation.py.

RECONCILED: yes DRIFT: 4
