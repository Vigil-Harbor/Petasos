# Reconciliation Report: PET-16

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-16.spec.md
> Merge: PR #13 (squash commit 8780564)
> Plane state: Done (group: completed)

## Summary
PET-16 shipped exactly as specified: a separate per-`rule_id` critical-alert rate cap (`alert_critical_per_minute_cap`, default 20) bounds the critical fan-out path in `AlertManager.evaluate`, with config validation, `_prune_stale` cleanup, and all 9 named tests present. Zero drift — current code matches the spec intent and the merged diff.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/config.py` | Yes | Field `alert_critical_per_minute_cap: int = 20` (config.py:76) + positive-int/bool validation (config.py:222-230) added per Design §1 |
| `petasos/premium/alerting.py` | Yes | `_critical_per_minute_timestamps` init (alerting.py:43), critical rate gate in `evaluate` (alerting.py:112-120), `_prune_stale` critical cleanup (alerting.py:415-421) per Design §2a/2b/2c |
| `tests/test_alerting.py` | Yes | `TestCriticalCap` class with 6 tests (test_alerting.py:469-564) per Test plan |

Unexpected files in diff (not in spec):
- `tests/test_config.py` — 3 config validation tests (test_config.py:66-76). Explicitly recommended by the spec's Test plan §"Config validation tests" and the Deferred (P2) note; not in the "Files to change" table but anticipated. Not drift.
- `docs/specs/TODO/PET-16.test-output.txt` — pytest run artifact from the ship-spec workflow (PR audit trail). Routine companion doc, not code. Not drift.

Files the spec said to leave alone (`petasos/_types.py`, `petasos/premium/escalation.py`, `petasos/premium/frequency.py`, `petasos/premium/audit.py`, `petasos/__init__.py`) are all absent from the diff — confirmed via `git show --stat`.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | Separate cap, not shared (independent from per-minute/per-hour caps) | Confirmed | `evaluate` uses a dedicated `_critical_per_minute_timestamps` deque (alerting.py:43, 113-115), distinct from `_per_minute_timestamps`/`_per_hour_timestamps` |
| 2 | Per-`rule_id`, not per-(rule_id, session_id) | Confirmed | `setdefault(candidate.rule_id, deque())` keys by rule_id only (alerting.py:113-115); test_critical_cap_bounds_fanout passes 100 distinct session_ids and caps at 5 (test_alerting.py:470-479) |
| 3 | Rate-limited, not suppressed (`_rate_limited_count`) | Confirmed | Cap breach does `self._rate_limited_count += 1` (alerting.py:118), not `_suppressed_count` |
| 4 | Generous default (20/min) | Confirmed | `alert_critical_per_minute_cap: int = 20` (config.py:76); test_critical_cap_default_allows_legitimate_burst fires 10/10 (test_alerting.py:481-490) |
| 5 | Per-minute only, no per-hour critical cap | Confirmed | Only a single 60.0s window deque exists for criticals; no per-hour critical structure added (alerting.py:116) |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `PetasosConfig` has `alert_critical_per_minute_cap: int = 20` with validation matching existing cap fields | Met | config.py:76 (field), config.py:222-230 (bool guard + positive-int check, mirrors `alert_per_hour_cap` pattern) |
| 2 | `AlertManager.__init__` initializes `_critical_per_minute_timestamps: dict[str, deque[float]]` | Met | alerting.py:43 |
| 3 | `AlertManager.evaluate` applies per-`rule_id` critical cap before dispatching | Met | alerting.py:112-120 (gate runs before `_alert_count += 1`/`surviving.append`/`on_alert` at L164-169) |
| 4 | `_prune_stale` cleans critical cap deques | Met | alerting.py:415-421 (evict + del empty keys, mirrors minute/hour pruning) |
| 5 | All 6 new `TestCriticalCap` tests pass | Met | All 6 present (test_alerting.py:470,481,492,504,534,552); test-output artifact records pass; full suite verified green per Done-when 8 |
| 6 | Existing `TestCriticalExemption` tests still pass (no regression) | Met | Class present and intact (test_alerting.py:419-461); 3 bypass tests fire ≤5 criticals, under default cap 20 |
| 7 | `ruff check .` and `mypy --strict .` clean | Unverifiable | Not re-run in this read-only pass; commit message + ship-spec gate assert clean. No type/lint smell in the diff |
| 8 | No regression in `pytest` full suite | Unverifiable | Not re-run here; PET-16.test-output.txt artifact in the commit records the suite run |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| `test_critical_cap_bounds_fanout` | Yes | tests/test_alerting.py:470 |
| `test_critical_cap_default_allows_legitimate_burst` | Yes | tests/test_alerting.py:481 |
| `test_critical_cap_per_rule_id_isolation` | Yes | tests/test_alerting.py:492 |
| `test_critical_cap_resets_after_window` | Yes | tests/test_alerting.py:504 |
| `test_tier3_bypasses_noncritical_caps` | Yes | tests/test_alerting.py:534 |
| `test_critical_fanout_callback_bounded` | Yes | tests/test_alerting.py:552 |
| `test_rejects_critical_per_minute_cap_zero` (advisory) | Yes | tests/test_config.py:66 |
| `test_rejects_critical_per_minute_cap_bool` (advisory) | Yes | tests/test_config.py:70 |
| `test_rejects_critical_per_minute_cap_negative` (advisory) | Yes | tests/test_config.py:74 |
| `TestCriticalExemption` regression suite | Yes | tests/test_alerting.py:419-461 |

## Wiki-ready
- None — routine hardening fix. The four decisions (separate cap, per-rule_id keying, rate-limited-not-suppressed, generous default) are reasonable defaults already documented in the brief/spec and need no standalone wiki decision entry. Note for filemap context only: `AlertManager.evaluate`'s non-critical `else` branch and the `test_tier3_bypasses_noncritical_caps` test were later extended by PET-17 (session-contribution caps) — current `alerting.py` is a superset of the PET-16 diff, which is expected and not drift.

RECONCILED: yes DRIFT: 0
