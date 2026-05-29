# PET-16 — ALRT-01: Cap Critical Alert Path to Prevent Unbounded Fan-out

**Plane:** PET-16 · **Finding:** ALRT-01 · **Priority:** High  
**OWASP:** ASI07 — Denial of service through resource exhaustion  
**Parent:** PET-14 · **Blocks:** PET-12 (release)  
**Status:** refuted → ready-for-dev

---

## Problem

`AlertManager.evaluate` at L93–123 of `petasos/premium/alerting.py` splits alert candidates into two paths: non-critical alerts pass through cooldown dedup (L98–104), per-minute caps (L106–110), and per-hour caps (L112–116). Critical alerts (`candidate.severity == "critical"`) skip all three gates and proceed directly to `surviving.append` + `on_alert` dispatch at L122–129.

The `_check_tier_escalation` method (L133–173) emits a critical alert every time `freq_result.tier == "tier3"` and the previous score maps to a lower tier. An attacker who rotates `session_id` values — each with a frequency score that crosses the tier3 threshold — generates one critical `tier_escalation` alert per session per `evaluate()` call. Because the critical path has zero rate limiting, the `on_alert` callback fans out without bound: 1,000 rotated sessions = 1,000 callback invocations in a single pipeline pass.

The existing test `test_tier3_bypasses_per_minute_cap` (`tests/test_alerting.py:430–439`) explicitly asserts this behavior — 5 consecutive tier3 evaluations produce 5 critical alerts with `alert_per_minute_cap=1`. The test proves the bypass is intentional but does not cap the upper bound.

## Prior Art

Drawbridge's TypeScript `AlertManager` (`clawmoat-drawbridge-sanitizer/src/alerting/index.ts:179`) also exempts critical alerts from rate limiting: `if (alert.severity !== "critical" && this.isRateLimited())`. However, Drawbridge processes one audit event per `evaluate()` call (L128), so the fan-out is structurally bounded to one alert per invocation. Petasos's `evaluate()` fans out to five candidate checks per call (L71–91), and the critical exemption applies to each surviving candidate — a wider blast radius than Drawbridge's single-event model.

The Drawbridge dedup layer (`isDuplicate`, L459–484) keys on `ruleId|sessionId`, which means distinct session IDs bypass dedup even for the same rule. Petasos mirrors this with `(candidate.rule_id, session_id)` at L98 — but only for the non-critical path. Critical alerts have no dedup at all.

## Remediation

### Approach: Add a per-rule_id critical cap (separate from the non-critical caps)

Critical alerts must never be silently dropped (Tier 3 cannot be disabled — design invariant), but the fan-out rate can be bounded. Introduce a `alert_critical_per_minute_cap` config field with a generous default (e.g., 20) that limits how many critical alerts of the same `rule_id` fire per minute. This preserves the guarantee that Tier 3 alerts are never suppressed by non-critical rate limits, while preventing unbounded callback storms.

### Changes

**1. `petasos/config.py` — new config field**

Add to `PetasosConfig`:

```python
alert_critical_per_minute_cap: int = 20
```

Default of 20 is well above any legitimate burst (a real tier3 escalation fires once per session per crossing) but caps adversarial rotation.

**2. `petasos/premium/alerting.py` — critical-path rate gate**

Add a `_critical_per_minute_timestamps` dict in `__init__`:

```python
self._critical_per_minute_timestamps: dict[str, deque[float]] = {}
```

In the `evaluate` method, replace the unconditional critical pass-through at L95–121 with:

```python
if is_critical:
    crit_deque = self._critical_per_minute_timestamps.setdefault(
        candidate.rule_id, deque()
    )
    self._evict_old(crit_deque, now, 60.0)
    if len(crit_deque) >= self._config.alert_critical_per_minute_cap:
        self._rate_limited_count += 1
        continue
    crit_deque.append(now)
else:
    # existing non-critical dedup + rate limiting
    ...
```

**3. `petasos/premium/alerting.py` — prune critical deques in `_prune_stale`**

Add cleanup of `_critical_per_minute_timestamps` alongside the existing minute/hour pruning (~L329–335):

```python
stale_crit_keys: list[str] = []
for ck, cd in self._critical_per_minute_timestamps.items():
    self._evict_old(cd, now, 60.0)
    if not cd:
        stale_crit_keys.append(ck)
for ck in stale_crit_keys:
    del self._critical_per_minute_timestamps[ck]
```

### Tests Required

| Test | File | Asserts |
|------|------|---------|
| `test_critical_cap_bounds_fanout` | `tests/test_alerting.py` | 100 rotated session tier3 evaluations produce <= `alert_critical_per_minute_cap` critical alerts |
| `test_critical_cap_default_allows_legitimate_burst` | `tests/test_alerting.py` | 10 sequential tier3 escalations (default cap=20) all fire — no false suppression |
| `test_critical_cap_per_rule_id_isolation` | `tests/test_alerting.py` | Different critical `rule_id` values each get their own cap budget |
| `test_critical_cap_resets_after_window` | `tests/test_alerting.py` | After 60s elapses (mocked), critical cap budget replenishes |
| `test_tier3_bypasses_noncritical_caps` | `tests/test_alerting.py` | Existing tests (`test_tier3_bypasses_cooldown`, `test_tier3_bypasses_per_minute_cap`, `test_tier3_bypasses_per_hour_cap`) still pass — critical alerts are exempt from non-critical limits |
| `test_critical_fanout_callback_bounded` | `tests/test_alerting.py` | With `on_alert` callback, 200 rotated-session tier3 evals invoke callback <= cap times |

### What existing tests need

`test_tier3_bypasses_per_minute_cap` currently asserts 5 critical alerts from 5 evaluations with `alert_per_minute_cap=1`. This test remains valid — the non-critical per-minute cap must not affect critical alerts. The new critical-specific cap is a separate limit.

## Decisions Carried Forward

- **Separate cap, not shared.** The critical cap (`alert_critical_per_minute_cap`) is independent from `alert_per_minute_cap` and `alert_per_hour_cap`. Sharing would re-introduce the risk of non-critical volume starving critical alerts.
- **Per-rule_id, not per-(rule_id, session_id).** The attack vector is session rotation; keying by session would not help. The cap must aggregate across all sessions for a given rule.
- **Rate-limited, not suppressed.** Critical alerts that exceed the cap increment `_rate_limited_count`, not `_suppressed_count`. They are volume-capped, not dedup-suppressed — the distinction matters for observability.
- **Generous default (20/min).** A legitimate deployment should never see 20 distinct tier3 crossings per minute. If it does, 20 alerts in that minute is sufficient signal; the 21st is noise.

## Done When

- [ ] `PetasosConfig` has `alert_critical_per_minute_cap: int = 20`
- [ ] `AlertManager.evaluate` applies per-`rule_id` critical cap before dispatching
- [ ] `_prune_stale` cleans critical cap deques
- [ ] All 6 new tests pass
- [ ] Existing `TestCriticalExemption` tests still pass (no regression)
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of Scope

- Adaptive / dynamic cap adjustment based on observed attack patterns (future work)
- Per-hour critical cap (per-minute is sufficient given the attack cadence)
- Callback timeout or async dispatch (separate concern — tracked under pipeline resilience)
- Drawbridge backport (uncoupled; own ticket if needed)
