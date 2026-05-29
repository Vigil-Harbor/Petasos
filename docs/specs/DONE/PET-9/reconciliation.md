# Reconciliation Report: PET-9

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-9.spec.md
> Merge: PR #8 (squash commit 823ecda, ancestor of master)
> Plane state: Done (group: completed)

## Summary

PET-9 shipped both premium modules (`AuditEmitter`, `AlertManager`), the type
exports, config fields, and pipeline wiring; all 13 "Done when" criteria are met
with ≥110 tests. Three spec **Decisions** drifted in implementation — the premium
manifest stayed three-value (brief, not spec), audit `sequence_number` became a
single global counter (not per-session), and the Tier-3 critical exemption is
capped rather than unconditional — all deliberate, tested choices that diverge
from the written spec.

## Scope

| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/premium/audit.py` (create) | Yes | `AuditEmitter` + payload builder. Implementation diverges from spec on sequence-counter design (see Decisions). |
| `petasos/premium/alerting.py` (create) | Yes | `AlertManager` + 5 rules. `_SEVERITY_RANK` defined locally (per edge-cases R3/F-1), not imported from pipeline.py. |
| `tests/test_audit.py` (create) | Yes | 27 tests (spec asked ≥25). |
| `tests/test_alerting.py` (create) | Yes | 61 tests (spec asked ≥25). |
| `petasos/_types.py` (modify) | Yes | `AuditEvent` + `Alert` frozen dataclasses, `MappingProxyType` payloads — matches spec exactly (_types.py:171-189). |
| `petasos/premium/__init__.py` (modify) | Yes | Re-exports `AuditEmitter`, `AlertManager`, `AuditEvent`, `Alert` (__init__.py:1-3, 21-24). |
| `petasos/pipeline.py` (modify) | Yes | Hooks implemented, feature gates added, `_build_premium_features` updated. Manifest is 3-value (drift). |
| `petasos/config.py` (modify) | Yes | Audit + alert fields added with validation; 3 fields beyond spec (see below). |
| `petasos/__init__.py` (modify) | Yes | Re-exports all four symbols in `__all__` (__init__.py:1-12, 24-54). |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-9.test-output.txt` — captured pytest output artifact (audit trail, not code; benign).
- `tests/test_pipeline.py` — 8-line edit to update two existing tests for the new `freq_result` hook signature (necessary follow-on, flagged in commit message).
- `tests/test_premium_integration.py` — extended with audit/alert integration tests (the spec's "Integration tests" section explicitly targets this file, so expected).

## Decisions

| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | Callback raises wrapped `RuntimeError`, surfaced by pipeline try/except | Drifted | Shipped emitter/manager do NOT re-raise; they catch `BaseException` and store `last_callback_error`/`callback_errors` (audit.py:62-68, alerting.py:170-179). Hooks return error strings that the pipeline appends to `errors` (pipeline.py:533-535, 541-542). End behavior (errors land in `result.errors`) is preserved, but the mechanism differs from the spec text and follows edge-cases R3/F-2 (per-alert try/except, accumulate, no mid-iteration abort). |
| 2 | Tier escalation detects decay-through-boundary re-entries; none→tier1 warning, tier3 critical | Confirmed | `_check_tier_escalation` compares `evaluate_tier(freq_result.previous_score)` to `freq_result.tier`; severity_map tier1=warning/tier2=high/tier3=critical (alerting.py:193-204). Test `test_decay_re_entry_fires` (test_alerting.py:139). |
| 3 | `time.monotonic()` for rate limiting, `time.time()` for event timestamps | Confirmed | `evaluate()` uses `now = time.monotonic()` (alerting.py:82); all `Alert.timestamp`/`AuditEvent.timestamp` use `time.time()` (alerting.py:210, audit.py:50). |
| 4 | Alert rule thresholds configurable via PetasosConfig | Confirmed (with additions) | All 11 spec'd fields present (config.py:73-89). PLUS 3 unspec'd fields: `alert_critical_per_minute_cap`, `alert_per_session_contribution_cap`, `alert_max_session_contribution_entries` (config.py:76, 85-86) — see Acceptance #9 and Unexpected note. |
| 5 | Sync callbacks, not async | Confirmed | `on_audit: Callable[[AuditEvent], None]`, `on_alert: Callable[[Alert], None]` (audit.py:26, alerting.py:36); no `await` on callbacks. |
| 6 | Two-value premium manifest (`"unlocked"`/`"locked"`), NOT three | Drifted | Shipped `_build_premium_features` returns three values: `"available"`/`"disabled"`/`"locked"` (pipeline.py:295-313). Integration tests assert `== "available"` and `== "disabled"` (test_premium_integration.py:109-111, 452, 468-469). This is the BRIEF's three-value scheme (brief line 128), the opposite of the spec's stated decision. Correctness R2/F-2 "three-value premium manifest unaddressed" was CLOSED in favor of the brief. |
| 7 | Instantiate modules eagerly, gate at call time | Confirmed | `self._audit_emitter` / `self._alert_manager` built unconditionally in `__init__` (pipeline.py:229-230); hooks short-circuit via `_check_premium` (pipeline.py:611-614, 624-627). |
| 8 | Callbacks on Pipeline, not PetasosConfig | Confirmed | `on_audit`/`on_alert` are `Pipeline.__init__` params (pipeline.py:195-196), threaded to modules (pipeline.py:229-230); absent from PetasosConfig (config.py). |
| — | Sequence number contract: per-session `dict[str, int]` keyed on session_id, `"__none__"` for null | Drifted | Shipped uses a single global counter `self._global_sequence: int` (audit.py:30, 44, 57). No per-session `_sequence_counters` dict, no `_last_emit_time`, no `"__none__"` sentinel, no TTL pruning — all described in spec §3 (lines 94-96, 124-126, 211) but absent. Tests were written to the global design: `test_different_sessions_global_sequence`, `test_none_session_shares_global_counter`, `test_global_sequence_continues_across_sessions` (test_audit.py:184, 193, 318). Deliberate redesign, but contradicts spec. |

## Acceptance Criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `audit.py` with `AuditEmitter` passing `mypy --strict` | Met | audit.py:21; commit message and PET-9.test-output.txt record the gate passing. |
| 2 | `alerting.py` with `AlertManager` passing `mypy --strict` | Met | alerting.py:31; follow-up commit 5e4266d explicitly resolved tuple-keyed-dict mypy errors. |
| 3 | `AuditEvent` + `Alert` exported from `_types.py` | Met | _types.py:171-189; re-exported in both `__init__.py` files. |
| 4 | Events emitted at each verbosity with correct payload depth (tested) | Met | `_build_payload` minimal/standard/verbose (audit.py:78-110); tests `test_minimal_payload_keys`/`test_standard_payload_keys`/`test_verbose_payload_keys` (test_audit.py:105,110,117). |
| 5 | Sequence numbers monotonic per session with no gaps (tested) | Met (semantics changed) | Monotonic + no-gap is satisfied via a GLOBAL counter; `test_no_gaps_across_100_emits` (test_audit.py:202), `test_sequential_emits_monotonic` (179). Note: "per session" was reinterpreted as global (see Decisions, last row). Criterion text is technically met for monotonicity/no-gaps. |
| 6 | All 5 alert rules fire correctly (tested) | Met | tier_escalation/high_severity_finding/rapid_fire/cross_session_burst/pii_volume_spike all have firing tests (test_alerting.py:102-321). |
| 7 | Rate limiting bounds 100 rapid triggers (tested) | Met | `test_100_rapid_triggers_bounded` (test_alerting.py:392), `test_critical_fanout_callback_bounded` (552). |
| 8 | Cross-session burst across ≥3 session IDs (tested) | Met | `_check_cross_session_burst` distinct-session tracker (alerting.py:293-344); `test_at_threshold_fires`/`test_duplicate_sessions_count_as_one` (test_alerting.py:259,274). |
| 9 | Tier 3 alerts bypass rate limit unconditionally (tested) | Met (with deviation) | Criticals bypass cooldown + per-minute + per-hour + session caps (alerting.py:112-120): `test_tier3_bypasses_cooldown/_per_minute_cap/_per_hour_cap` (test_alerting.py:420,430,441). Deviation: criticals are NOT fully unconditional — they hit `alert_critical_per_minute_cap` (default 20) (alerting.py:117-119), contradicting spec/brief "bypass ALL rate limiting." Bounded by `test_critical_cap_bounds_fanout` (470). Done-when text "bypass rate limit" is met for the three named limiters; the new critical cap is an added safety bound. |
| 10 | Callbacks invoked; exceptions swallowed gracefully (tested) | Met | audit.py:59-68, alerting.py:167-179; `test_callback_raises_valueerror_swallowed` (test_audit.py:226), `test_callback_exception_logs_and_continues` (test_alerting.py:611). |
| 11 | Pipeline stubs replaced; audit/alert fire when enabled (integration tested) | Met | Hooks call `emit`/`evaluate` (pipeline.py:615, 628); `test_audit_enabled_emits_events`/`test_alerting_enabled_fires_on_trigger` (test_premium_integration.py:403,412). |
| 12 | ≥50 tests across audit + alerting | Met | 27 (audit) + 61 (alerting) = 88 module tests; commit message reports 110 incl. integration. |
| 13 | `ruff check`, `ruff format`, `mypy --strict` pass | Met | PET-9.test-output.txt artifact + dedicated fix commits (a931331, 5e4266d) closing lint/type findings. |

## Test Plan

| Test | Exists? | Location |
|---|---|---|
| AuditEvent frozen / fields / uuid4 | Yes | test_audit.py:70, 82, 92 |
| Verbosity minimal/standard/verbose payload keys | Yes | test_audit.py:105, 110, 117, 134 |
| Sequence: first=0, monotonic, no gaps over 100 | Yes | test_audit.py:174, 179, 202 |
| Sequence: different/none sessions (re-spec'd to global) | Yes | test_audit.py:184, 193, 277, 318 |
| Audit callback None / exact / raises ValueError / Exception | Yes | test_audit.py:214, 219, 226, 237 |
| Audit event_type=scan_complete; empty findings; freq_result None | Yes | test_audit.py:254, 266, 271 |
| Alert frozen / fields | Yes | test_alerting.py:69, 82 |
| tier_escalation none→t1 / t1→t2 / t2→t3 / same / freq None / decay re-entry | Yes | test_alerting.py:102, 110, 118, 126, 133, 139 |
| high_severity_finding fires / medium-no / critical / configurable | Yes | test_alerting.py:161, 168, 175, 182 |
| rapid_fire threshold / window / session-scope / skip None | Yes | test_alerting.py:196, 203, 212, 222, 228 |
| cross_session_burst <N / ≥N / dup-as-one / None excluded | Yes | test_alerting.py:251, 259, 274, 283 |
| pii_volume_spike <thr / ≥thr / window expiry | Yes | test_alerting.py:299, 307, 321 |
| Rate limiting cooldown / per-minute / per-hour / 100-bounded / counts | Yes | test_alerting.py:350, 361, 376, 392, 406 |
| Critical exemption bypass cooldown/minute/hour + non-crit still limited | Yes | test_alerting.py:420, 430, 441, 452 |
| Ring buffer maxlen / shape | Yes | test_alerting.py:573, 581 |
| Alert callback None / each / exception | Yes | test_alerting.py:598, 604, 611 |
| Stats alert/suppressed/rate_limited counts | Yes | test_alerting.py:638, 645, 652 |
| Integration: audit/alert enabled/disabled, manifest, callback errors, tier3 | Yes | test_premium_integration.py:403, 412, 421, 429, 446, 454, 471, 481, 499 |

## Wiki-ready

- **Premium manifest reverted to three-value scheme** — the spec's Decision to keep the two-value (`unlocked`/`locked`) scheme was overruled during implementation in favor of the brief's three-value (`available`/`disabled`/`locked`) scheme. This is a constraining, consumer-visible contract decision that contradicts the written spec; the wiki/decisions layer should record which scheme is canonical so PET-10 and frontend binding consume the correct values.
- **Audit `sequence_number` is global, not per-session** — reusable design fact: gap-free monotonic ordering is guaranteed across the whole emitter, not per session_id. Consumers that assumed per-session sequencing (per spec) will be surprised. Worth a decision note since the spec's "per-session counter + `__none__` sentinel + TTL pruning" design was dropped entirely.
- **Tier-3 critical alerts have a per-minute fan-out cap** — the "Tier 3 bypasses ALL rate limiting" invariant was softened to "bypasses cooldown/per-minute/per-hour/session caps but is bounded by `alert_critical_per_minute_cap` (default 20)" to prevent critical-alert storms. Constraining; contradicts the brief's hardcoded-invariant framing.

RECONCILED: yes DRIFT: 4
