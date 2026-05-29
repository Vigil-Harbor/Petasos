# PET-16 — Cap Critical Alert Path to Prevent Unbounded Fan-out

**Ticket:** PET-16 · **Finding:** ALRT-01 · **Priority:** High
**Parent:** PET-14 · **Blocks:** PET-12 (release)

---

## Goal

Add a per-`rule_id` critical-alert rate cap to `AlertManager.evaluate` so that an attacker rotating `session_id` values across tier-3 crossings cannot trigger unbounded `on_alert` callback invocations. Critical alerts remain exempt from the non-critical cooldown, per-minute, and per-hour gates — but are now bounded by their own separate per-minute cap (`alert_critical_per_minute_cap`, default 20).

## Scope

### Files to change

| File | What changes |
|------|-------------|
| `petasos/config.py` | Add `alert_critical_per_minute_cap: int = 20` field + validation |
| `petasos/premium/alerting.py` | Add `_critical_per_minute_timestamps` dict; gate critical candidates through per-`rule_id` cap; prune critical deques in `_prune_stale` |
| `tests/test_alerting.py` | Add 6 new tests in a `TestCriticalCap` class |

### Files to leave alone

| File | Reason |
|------|--------|
| `petasos/_types.py` | `Alert` dataclass unchanged — no new fields needed |
| `petasos/premium/escalation.py` | Escalation logic is upstream of alerting; no changes |
| `petasos/premium/frequency.py` | Frequency scoring unchanged |
| `petasos/premium/audit.py` | Audit emission unchanged |
| `petasos/__init__.py` | No new public exports |

## Decisions

### Decision 1: Separate cap, not shared

The critical cap (`alert_critical_per_minute_cap`) is independent from `alert_per_minute_cap` and `alert_per_hour_cap`. Sharing would re-introduce the risk of non-critical volume starving critical alerts. The brief explicitly requires this separation.

### Decision 2: Per-rule_id, not per-(rule_id, session_id)

The attack vector is session rotation; keying the cap by `(rule_id, session_id)` would not bound the fan-out because each rotated session gets its own budget. The cap must aggregate across all sessions for a given `rule_id`.

### Decision 3: Rate-limited, not suppressed

Critical alerts that exceed the cap increment `_rate_limited_count`, not `_suppressed_count`. They are volume-capped, not dedup-suppressed — the distinction matters for observability. The brief carries this forward explicitly.

### Decision 4: Generous default (20/min)

A legitimate deployment should never see 20 distinct tier-3 crossings per minute. If it does, 20 alerts in that minute is sufficient signal. The brief sets this default.

### Decision 5: Per-minute only, no per-hour critical cap

The brief explicitly places a per-hour critical cap out of scope. The per-minute window is sufficient given the attack cadence (session rotation at tier-3 crossing).

## Design

### 1. Config field (`petasos/config.py`)

Add to `PetasosConfig` frozen dataclass, in the "Alerting thresholds" group after `alert_per_hour_cap`:

```python
alert_critical_per_minute_cap: int = 20
```

Add validation in `__post_init__` alongside the existing alerting validators (after the `alert_per_hour_cap` check, around L170):

```python
if (
    not isinstance(self.alert_critical_per_minute_cap, int)
    or isinstance(self.alert_critical_per_minute_cap, bool)
    or self.alert_critical_per_minute_cap <= 0
):
    raise ValueError(
        f"alert_critical_per_minute_cap must be a positive integer, "
        f"got {self.alert_critical_per_minute_cap!r}"
    )
```

This follows the exact pattern used for `alert_per_minute_cap` and `alert_per_hour_cap` (bool guard, positive-int check, descriptive error). The field is included in `to_dict` / `from_dict` / `copy` automatically via the `fields()` iteration.

### 2. Critical rate gate (`petasos/premium/alerting.py`)

**2a. New instance state in `__init__`:**

Add after `self._per_hour_timestamps` (L41):

```python
self._critical_per_minute_timestamps: dict[str, deque[float]] = {}
```

**2b. Gate in `evaluate` method:**

Replace the unconditional critical pass-through at L95–121. Currently:

```python
if not is_critical:
    # ... dedup + rate limiting for non-critical ...
    ...
# (critical falls through to surviving.append)
```

Change to:

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
    # existing non-critical dedup + rate limiting (unchanged)
    dedup_key = (candidate.rule_id, session_id)
    last_fire = self._rule_cooldowns.get(dedup_key)
    cooldown = self._config.alert_cooldown_seconds
    if last_fire is not None and (now - last_fire) < cooldown:
        self._suppressed_count += 1
        continue
    minute_deque = self._per_minute_timestamps.setdefault(candidate.rule_id, deque())
    self._evict_old(minute_deque, now, 60.0)
    if len(minute_deque) >= self._config.alert_per_minute_cap:
        self._rate_limited_count += 1
        continue
    hour_deque = self._per_hour_timestamps.setdefault(candidate.rule_id, deque())
    self._evict_old(hour_deque, now, 3600.0)
    if len(hour_deque) >= self._config.alert_per_hour_cap:
        self._rate_limited_count += 1
        continue
    self._rule_cooldowns[dedup_key] = now
    minute_deque.append(now)
    hour_deque.append(now)
```

The critical path now has its own rate gate that:
- Is keyed by `rule_id` only (not session_id) — Decision 2
- Uses a separate deque from non-critical — Decision 1
- Increments `_rate_limited_count` on cap breach — Decision 3
- Uses 60-second window via `_evict_old` — consistent with non-critical minute cap mechanics

**2c. Prune critical deques in `_prune_stale`:**

Add after the existing hour-key pruning block (~L337–343):

```python
stale_crit_keys: list[str] = []
for ck, cd in self._critical_per_minute_timestamps.items():
    self._evict_old(cd, now, 60.0)
    if not cd:
        stale_crit_keys.append(ck)
for ck in stale_crit_keys:
    del self._critical_per_minute_timestamps[ck]
```

This prevents unbounded growth of the `_critical_per_minute_timestamps` dict when many distinct `rule_id` values cycle through. The pattern matches the existing minute/hour pruning exactly.

### 3. Tests (`tests/test_alerting.py`)

Add a new `TestCriticalCap` class after `TestCriticalExemption`. Six tests:

| # | Test name | What it verifies |
|---|-----------|-----------------|
| 1 | `test_critical_cap_bounds_fanout` | 100 rotated-session tier-3 evaluations produce `<= alert_critical_per_minute_cap` critical alerts |
| 2 | `test_critical_cap_default_allows_legitimate_burst` | 10 sequential tier-3 escalations (default cap=20) all fire — no false suppression |
| 3 | `test_critical_cap_per_rule_id_isolation` | Different critical `rule_id` values each get their own cap budget |
| 4 | `test_critical_cap_resets_after_window` | After 60s elapses (mocked `time.monotonic`), critical cap budget replenishes |
| 5 | `test_tier3_bypasses_noncritical_caps` | Existing `TestCriticalExemption` tests (`test_tier3_bypasses_cooldown`, `test_tier3_bypasses_per_minute_cap`, `test_tier3_bypasses_per_hour_cap`) still pass — critical alerts exempt from non-critical limits |
| 6 | `test_critical_fanout_callback_bounded` | With `on_alert` callback, 200 rotated-session tier-3 evals invoke callback `<= cap` times |

**Test 3 detail — per-rule_id isolation:** This test requires two different critical alert candidates from a single `evaluate()` call. Today only `_check_tier_escalation` can produce a critical alert (the others are "warning" or "high"). To test per-`rule_id` isolation, the test will make two consecutive calls: one that triggers a critical `tier_escalation` and a separate call that triggers a critical `high_severity_finding` (by configuring `alert_high_severity_threshold="critical"` so a critical-severity finding emits a `high_severity_finding` alert with severity "high" — but that's not critical). Actually, the simpler path: set `alert_critical_per_minute_cap=1`, fire one tier-3 crossing (critical `tier_escalation`), confirm it fires. Then fire another tier-3 crossing — it should be capped. But a *different* critical `rule_id` would still fire. Since only `tier_escalation` produces critical alerts in the current implementation, the test can verify isolation by confirming that if a hypothetical second critical rule_id existed, it would get its own budget. The pragmatic approach: directly invoke `evaluate` with a mocked candidate list that includes two critical alerts with distinct `rule_id` values, but this would require refactoring `evaluate`. Instead, test isolation via the internal dict: after one tier-3 evaluation, verify that `_critical_per_minute_timestamps["tier_escalation"]` has one entry and no other keys exist. Then confirm a non-`tier_escalation` critical rule_id would have a fresh budget by asserting the dict lookup returns an empty deque for an unknown key. This is a whitebox test but it verifies the per-`rule_id` keying.

**Test 4 detail — window reset:** Use `unittest.mock.patch("petasos.premium.alerting.time")` to control `time.monotonic()`. Fire `cap` alerts at `t=0`, confirm they all fire. Then fire one more at `t=0.5` — it should be rate-limited. Advance to `t=61` and fire again — it should fire (window expired).

**Test 5 detail — regression guard:** This is a meta-test confirming that the existing `TestCriticalExemption` tests still pass unmodified. The existing three tests (`test_tier3_bypasses_cooldown`, `test_tier3_bypasses_per_minute_cap`, `test_tier3_bypasses_per_hour_cap`) each fire <=5 critical alerts, well under the default cap of 20. They will pass without modification.

## Test plan

### New tests (6)

All in `tests/test_alerting.py` under a new `TestCriticalCap` class:

1. **`test_critical_cap_bounds_fanout`** — Create `AlertManager` with `alert_critical_per_minute_cap=5`. Fire 100 `evaluate()` calls each with a distinct `session_id` and a tier-3 `FrequencyUpdateResult`. Count critical `tier_escalation` alerts. Assert `<= 5`.

2. **`test_critical_cap_default_allows_legitimate_burst`** — Create `AlertManager` with default config (cap=20). Fire 10 `evaluate()` calls each with a distinct `session_id` and a tier-3 `FrequencyUpdateResult`. All 10 critical alerts must fire (no false suppression).

3. **`test_critical_cap_per_rule_id_isolation`** — Create `AlertManager` with `alert_critical_per_minute_cap=1`. Fire one tier-3 evaluation — critical `tier_escalation` fires. Fire another — rate-limited. Verify `_critical_per_minute_timestamps` is keyed by `"tier_escalation"` only. Confirm a fresh `rule_id` key would start with an empty budget (dict `.get()` returns `None`).

4. **`test_critical_cap_resets_after_window`** — Mock `time.monotonic`. Fire `cap` alerts at `t=base`. Advance to `t=base+61`. Fire again — it must fire (budget replenished).

5. **`test_tier3_bypasses_noncritical_caps`** — Set `alert_per_minute_cap=1`, `alert_per_hour_cap=1`, `alert_cooldown_seconds=9999`. Fire 3 tier-3 evaluations (well under critical cap=20). All 3 critical alerts must survive. This confirms the non-critical gates do not interfere with critical alerts.

6. **`test_critical_fanout_callback_bounded`** — Create `AlertManager` with `alert_critical_per_minute_cap=10` and an `on_alert` callback that appends to a list. Fire 200 rotated-session tier-3 evaluations. Assert callback invocation count for critical `tier_escalation` alerts `<= 10`.

### Existing test regression

The `TestCriticalExemption` tests fire at most 5 critical alerts per test, well under the default cap of 20. They will pass without modification. This is verified as test 5 above.

### Config validation tests

The existing config validation test patterns in `tests/test_config.py` (if present) should also cover the new field. Add:
- `test_critical_per_minute_cap_rejects_zero`
- `test_critical_per_minute_cap_rejects_bool`
- `test_critical_per_minute_cap_rejects_negative`

## Test command

```bash
C:\Users\zioni\Documents\Vigil-Harbor\Petasos\.venv\Scripts\python.exe -m pytest tests/test_alerting.py tests/test_config.py -v
```

## Done when

- [ ] `PetasosConfig` has `alert_critical_per_minute_cap: int = 20` with validation matching existing cap fields — maps to Design §1
- [ ] `AlertManager.__init__` initializes `_critical_per_minute_timestamps: dict[str, deque[float]]` — maps to Design §2a
- [ ] `AlertManager.evaluate` applies per-`rule_id` critical cap before dispatching — maps to Design §2b
- [ ] `_prune_stale` cleans critical cap deques — maps to Design §2c
- [ ] All 6 new `TestCriticalCap` tests pass — maps to Test plan
- [ ] Existing `TestCriticalExemption` tests still pass (no regression) — maps to Test plan §regression
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Deferred (P2+)

Advisory findings from round-1 review (P0/P1 = 0, spec green at round 1):

- **Config validation tests not in Done-when** (correctness P2, edge-cases P3): The 3 proposed `test_config.py` tests are not counted in the "6 new tests" figure or the Done-when criteria. Implementer should add them but they are not gating.
- **Test 3 per-rule_id isolation is a whitebox structural test** (edge-cases P2): Only `tier_escalation` produces critical alerts today, so the test verifies dict keying rather than full behavioral isolation. Acceptable given current rule set.
- **Thread safety of `AlertManager.evaluate`** (edge-cases P2): Pre-existing — no locking on shared state. Pipeline operates on a single asyncio event loop; thread-safe locking is a separate concern if needed.
- **`on_alert` callback exception consumes critical budget** (edge-cases P2): `crit_deque.append(now)` happens before the callback. If callback raises, one budget unit is consumed. Matches non-critical path behavior — accepted.
- **No test for `_prune_stale` cleaning critical deques** (edge-cases P2): Done-when says `_prune_stale` cleans critical deques but no test verifies dict key removal. Implementer should consider a 7th test verifying key cleanup after window expiry.
- **Test command path inconsistency** (conventions P2): `.venv\Scripts\python.exe` diverges from sibling specs. Implementer should use whichever interpreter is on PATH.
- **Test 3 detail narrative is verbose** (conventions P2): The stream-of-consciousness in the Design section (Test 3 detail) should be read alongside the cleaner Test plan description at the end.

## Out of scope

- Adaptive / dynamic cap adjustment based on observed attack patterns (future work)
- Per-hour critical cap (per-minute is sufficient given the attack cadence)
- Callback timeout or async dispatch (separate concern — tracked under pipeline resilience)
- Drawbridge backport (uncoupled; own ticket if needed)
- Changes to `AuditEmitter` or audit event shape for rate-limited critical alerts (if needed, separate ticket)
- Thread safety of `AlertManager.evaluate` (pre-existing single-threaded assumption)
