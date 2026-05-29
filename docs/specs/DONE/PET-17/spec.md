# PET-17 — ALRT-02: Prevent Session Rotation from Starving Legitimate Alert Caps

**Plane:** PET-17 · **Finding:** ALRT-02 · **Priority:** High
**Parent:** PET-14 · **Blocks:** PET-12 (release)

---

## Goal

Add per-session contribution caps to `AlertManager` so that no single session — or coordinated set of throwaway sessions — can monopolize a rule's per-minute rate budget. This closes the ALRT-02 finding (OWASP ASI07: DoS through resource exhaustion) where an attacker generating many throwaway sessions exhausts the shared per-`rule_id` rate cap and suppresses legitimate alerts from real sessions.

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/config.py` | Add `alert_per_session_contribution_cap` and `alert_max_session_contribution_entries` fields with validation |
| `petasos/premium/alerting.py` | Add `_per_session_minute_timestamps` tracking dict, per-session contribution gate in `evaluate()`, pruning + memory-bound eviction in `_prune_stale()` |
| `tests/test_alerting.py` | 12 new tests + adjust 3 existing tests for cross-field validation |
| `tests/test_config.py` | 7 new config validation tests |

### Files to leave alone

- Critical alert path infrastructure in `alerting.py` (L93–96 loop setup, L122–129 alert acceptance + callback) — PET-16 scope
- `petasos/pipeline.py` — no pipeline-level changes
- Other premium modules (`frequency.py`, `escalation.py`, `profiles/`, `guard.py`, `audit.py`, `license.py`)
- All scanner implementations

### New files

None.

## Decisions

### D1: Additive layer, not replacement

The per-session contribution cap is a new gate inserted between the existing cooldown check (L98–104) and the global per-rule_id per-minute cap (L106–110). The global per-`rule_id` cap remains as the hard ceiling. This is defense-in-depth — the new layer reduces the attack surface, and the global layer remains as the ultimate rate bound.

**Rationale:** Replacing the global cap with a per-session one would change the semantics of the per-minute cap for all consumers. The additive approach is backward-compatible for any integration that doesn't trigger the session contribution limit.

### D2: Default contribution cap of 2, not 1

A legitimate session may cross a threshold, decay, and re-cross within the same minute (documented in `test_decay_re_entry_fires` at `tests/test_alerting.py:139`). A cap of 1 would suppress the re-entry alert. A cap of 2 allows one re-entry while still bounding throwaway-session attacks to `ceil(per_minute_cap / 2)` sessions to exhaust the budget.

### D3: Memory bound is mandatory — reject, don't evict

Without it, `_per_session_minute_timestamps` grows with O(rules * sessions) — the fix would introduce a new variant of the same attack class (memory exhaustion instead of rate-cap exhaustion). The bound is a hard cap on the number of tracking keys. When the dict is at capacity, **new sessions are rate-limited** rather than old entries evicted. This prevents an attacker from forcing eviction of legitimate sessions' tracking state (which would reset their contribution counts and defeat the protection). The brief proposed a hardcoded constant (10,000); this spec promotes it to a `PetasosConfig` field (`alert_max_session_contribution_entries`) for consistency with `max_sessions` and `alert_ring_buffer_capacity`, both of which are configurable bounds on memory growth.

### D4: Critical alerts are not affected

The per-session contribution cap only applies to the non-critical path (L97: `if not is_critical`). Critical path handling is PET-16's scope. This spec does not touch L93–96 or L122–129.

## Design

### 1. Config additions (`petasos/config.py`)

Add two fields to `PetasosConfig`:

```python
alert_per_session_contribution_cap: int = 2
alert_max_session_contribution_entries: int = 10_000
```

- `alert_per_session_contribution_cap` — max alerts a single `(rule_id, session_id)` pair can contribute to the global per-minute cap within a 60-second window. Must be a positive integer.
- `alert_max_session_contribution_entries` — hard cap on the number of keys in `_per_session_minute_timestamps`. When the dict is at capacity, new session keys are rejected (rate-limited) rather than old entries evicted. Must be a positive integer.

Place these fields in the existing "Alerting thresholds" section of `PetasosConfig`, after `alert_ring_buffer_capacity`.

Add validation in `__post_init__` after the `alert_ring_buffer_capacity` validation block (around L242), following the existing pattern (check `isinstance(…, int)`, exclude `bool`, check `> 0`):

```python
if (
    not isinstance(self.alert_per_session_contribution_cap, int)
    or isinstance(self.alert_per_session_contribution_cap, bool)
    or self.alert_per_session_contribution_cap <= 0
):
    raise ValueError(
        f"alert_per_session_contribution_cap must be a positive integer, "
        f"got {self.alert_per_session_contribution_cap!r}"
    )
if (
    not isinstance(self.alert_max_session_contribution_entries, int)
    or isinstance(self.alert_max_session_contribution_entries, bool)
    or self.alert_max_session_contribution_entries <= 0
):
    raise ValueError(
        f"alert_max_session_contribution_entries must be a positive integer, "
        f"got {self.alert_max_session_contribution_entries!r}"
    )
if self.alert_per_session_contribution_cap > self.alert_per_minute_cap:
    raise ValueError(
        f"alert_per_session_contribution_cap ({self.alert_per_session_contribution_cap}) "
        f"must be <= alert_per_minute_cap ({self.alert_per_minute_cap})"
    )
```

The cross-field validation ensures the session contribution cap does not exceed the per-minute cap. When `cap == per_minute_cap`, the session cap is a degenerate no-op (a single session can exhaust the global budget), but this is a valid configuration — particularly for `per_minute_cap=1` where no smaller positive integer exists. When `cap > per_minute_cap`, the config is nonsensical and rejected. The operator `>` (not `>=`) is used to allow equality, consistent with the existing cross-field validation pattern at `config.py:243` (`alert_rapid_fire_count > alert_ring_buffer_capacity`).

### 2. Session contribution tracking (`petasos/premium/alerting.py`)

Add new instance variables in `AlertManager.__init__`:

```python
self._per_session_minute_timestamps: dict[tuple[str, str | None], deque[float]] = {}
self._session_rate_limited_count: int = 0
```

The key is `(rule_id, session_id)` — the same composite key used by the cooldown dedup layer, but tracking contribution counts rather than last-fire timestamps. `session_id=None` maps to `(rule_id, None)`, ensuring that no-session calls share a contribution budget rather than being unbounded.

Expose `_session_rate_limited_count` as a read-only property alongside the existing `rate_limited_count`:

```python
@property
def session_rate_limited_count(self) -> int:
    return self._session_rate_limited_count
```

This allows operators to distinguish session-contribution-cap rejections from global per-minute/per-hour cap rejections when diagnosing rate limiting behavior.

### 3. Contribution gate in `evaluate()` — non-critical path

After the cooldown check passes (L104) but before the global per-minute cap check (L106), insert the per-session contribution gate:

```python
# Memory bound: if tracking dict is at capacity, rate-limit new sessions
# rather than evicting live entries (prevents attacker-controlled eviction)
session_minute_key = (candidate.rule_id, session_id)
if session_minute_key not in self._per_session_minute_timestamps:
    if len(self._per_session_minute_timestamps) >= self._config.alert_max_session_contribution_entries:
        self._session_rate_limited_count += 1
        continue

session_minute_deque = self._per_session_minute_timestamps.setdefault(
    session_minute_key, deque()
)
self._evict_old(session_minute_deque, now, 60.0)
if len(session_minute_deque) >= self._config.alert_per_session_contribution_cap:
    self._session_rate_limited_count += 1
    continue
```

After the global caps pass and the alert is accepted (after L120, before L122), append the timestamp:

```python
session_minute_deque.append(now)
```

The insertion order matters:
1. **Memory bound check first** — if the tracking dict is at capacity and this is a new session key, reject immediately. This prevents an attacker from forcing eviction of legitimate sessions' tracking state by flooding with throwaway sessions.
2. **Session contribution check second** — for sessions already being tracked, enforce the per-session per-minute budget.
3. **Global per-minute/per-hour checks last** — a session that hits its contribution cap or the memory bound doesn't consume a slot from the global budget.

Both the session contribution gate and the memory bound gate increment only `_session_rate_limited_count` — they do **not** increment `_rate_limited_count`. This preserves backward-compatible semantics: `rate_limited_count` continues to mean "global per-minute/per-hour cap rejections only." Operators who want total rejections can compute `rate_limited_count + session_rate_limited_count`.

Within a single `evaluate()` call, up to 5 candidates (one per rule) may each insert a new session key, temporarily overshooting `max_entries` by at most 5. This bounded overshoot is corrected on the next `_prune_stale()` call and does not affect the security guarantee (the overshoot is O(rules), not O(sessions)).

### 4. Pruning and memory bound in `_prune_stale()`

Add alongside the existing minute/hour pruning:

```python
stale_session_keys: list[tuple[str, str | None]] = []
for sk, sd in self._per_session_minute_timestamps.items():
    self._evict_old(sd, now, 60.0)
    if not sd:
        stale_session_keys.append(sk)
for sk in stale_session_keys:
    del self._per_session_minute_timestamps[sk]
```

No LRU eviction sort is needed. The memory bound is enforced at insertion time in `evaluate()` (section 3): when the dict is at capacity and a new key would be inserted, the alert is rate-limited instead. The `_prune_stale` loop above handles natural expiry — entries whose deques are empty after the 60s window eviction are removed, freeing capacity for new sessions. Under sustained attack (new sessions faster than 60s expiry), the dict stays at `max_entries` and new sessions are rejected, which is the correct behavior: the attacker pays the rate-limit cost, not the legitimate sessions.

### 5. Existing test adjustments

**`test_per_minute_cap`** (L361–374): Uses 5 distinct sessions (`s0`–`s4`) with `alert_per_minute_cap=2` and `alert_cooldown_seconds=0.001`. Default `per_session_contribution_cap=2` satisfies `2 <= 2` (equality allowed). Each session fires once, so the session cap is never reached. **Recommended but not required:** pass `alert_per_session_contribution_cap=1` to make the test's intent clearer (isolating global cap behavior).

**`test_100_rapid_triggers_bounded`** (L392–404): Uses 100 distinct sessions with `alert_per_minute_cap=5` and `alert_cooldown_seconds=0.001`. Each session fires one `high_severity_finding`. With `per_session_contribution_cap=2` (default), each session contributes at most 1 alert per call (single call each), so the global cap of 5 still governs. Assertion `total_fired <= 5` remains correct. **Verify, no change expected.** Note: the brief expected adjustment here, but analysis shows each session fires only once per `evaluate` call, so the per-session contribution cap (2) is never reached for single-call sessions.

**`test_per_hour_cap`** (L376–390): Uses 5 distinct sessions with `alert_per_hour_cap=2`, `alert_per_minute_cap=100`. With `per_minute_cap=100`, the default `per_session_contribution_cap=2` satisfies `2 <= 100`. **Verify, no change expected.**

**`test_tier3_bypasses_per_minute_cap`** (L430–439): Uses `alert_per_minute_cap=1`. Default `per_session_contribution_cap=2` violates `2 > 1`. Even though this test exercises the critical path (which bypasses session contribution checks), the cross-field validation fires at `PetasosConfig` construction time. **Adjustment required:** pass `alert_per_session_contribution_cap=1` explicitly.

**`test_rate_limited_count_reflects_caps`** (L538–549): Uses `alert_per_minute_cap=1, alert_cooldown_seconds=0.001`. Default `per_session_contribution_cap=2` violates `2 > 1`. **Adjustment required:** pass `alert_per_session_contribution_cap=1` explicitly.

**Systematic rule:** All existing tests that set `alert_per_minute_cap` to a value strictly below the default `alert_per_session_contribution_cap` (2) must also set `alert_per_session_contribution_cap` explicitly to a value `<= per_minute_cap`. Affected: `test_tier3_bypasses_per_minute_cap` (per_minute_cap=1), `test_rate_limited_count_reflects_caps` (per_minute_cap=1).

## Test plan

### New tests

| # | Test name | What it asserts |
|---|-----------|-----------------|
| 1 | `test_session_contribution_cap_limits_single_session` | Same session firing `high_severity_finding` repeatedly (with `alert_cooldown_seconds=0.001`) produces `<= alert_per_session_contribution_cap` alerts per minute, even when global cap is higher |
| 2 | `test_throwaway_sessions_cannot_exhaust_rule_cap` | 100 throwaway sessions with `per_session_contribution_cap=1`, `per_minute_cap=10` (non-default; set high to isolate session contribution behavior): after 10 throwaway sessions exhaust the cap, advancing time past 60s allows a legitimate session to alert |
| 3 | `test_session_contribution_independent_across_rules` | Session hitting `high_severity_finding` contribution cap can still fire `rapid_fire` alerts (different `rule_id`) |
| 4 | `test_session_contribution_window_resets` | After 60s (mocked via `time.monotonic`), session contribution budget replenishes and the session can alert again |
| 5 | `test_session_none_uses_none_key` | `session_id=None` sessions share a `(rule_id, None)` contribution key — firing `per_session_contribution_cap` times rate-limits subsequent None sessions |
| 6 | `test_per_session_deque_pruned` | After 60s elapses, `_per_session_minute_timestamps` entries with empty deques are cleaned up by `_prune_stale` |
| 7 | `test_memory_bound_rejects_new_sessions` | With `alert_max_session_contribution_entries=100` and 200 distinct sessions, new sessions beyond 100 are rate-limited (not evicted). `_per_session_minute_timestamps` stays at 100 entries. `session_rate_limited_count` increments for rejected sessions |
| 8 | `test_cap_1_suppresses_reentry` | With `per_session_contribution_cap=1` and low cooldown, same session crossing a threshold, decaying, and re-crossing within 60s has its second alert suppressed by the session contribution cap (validates D2 rationale) |
| 9 | `test_three_gate_composition` | Composite test with `cooldown=30s`, `per_session_contribution_cap=2`, `per_minute_cap=5`. Advances time through multiple cooldown and window boundaries, verifying the exact sequence of fires and suppressions across all three gates |
| 10 | `test_session_rate_limited_count_separate` | Verifies `session_rate_limited_count` increments independently of `rate_limited_count` for session-cap rejections vs global-cap rejections |
| 11 | `test_cross_field_validation_cap_gt_per_minute` | `alert_per_session_contribution_cap > alert_per_minute_cap` raises `ValueError`; `cap == per_minute_cap` is allowed |
| 12 | `test_memory_bound_recovery_after_expiry` | After dict reaches capacity and new sessions are rejected, advance time by 61s, verify `_prune_stale` clears stale entries and a new session is accepted again |

### Existing tests to verify

- `test_per_minute_cap` — verify unchanged behavior
- `test_100_rapid_triggers_bounded` — verify unchanged behavior
- `test_per_hour_cap` — verify unchanged behavior (same pattern as per_minute_cap)
- All `TestCriticalExemption` tests — verify critical path is unaffected

### Config validation tests

Add to the config test file:
- `test_alert_per_session_contribution_cap_rejects_zero` — `ValueError`
- `test_alert_per_session_contribution_cap_rejects_negative` — `ValueError`
- `test_alert_per_session_contribution_cap_rejects_bool` — `ValueError`
- `test_alert_max_session_contribution_entries_rejects_zero` — `ValueError`
- `test_alert_max_session_contribution_entries_rejects_negative` — `ValueError`
- `test_alert_max_session_contribution_entries_rejects_bool` — `ValueError`
- `test_cross_field_validation_cap_gt_per_minute` (also in test 11 above) — `cap > per_minute_cap` raises `ValueError`; `cap == per_minute_cap` is accepted

## Test command

```bash
python -m pytest tests/test_alerting.py tests/test_config.py -v
```

## Done when

- [ ] `PetasosConfig` has `alert_per_session_contribution_cap: int = 2` with validation
- [ ] `PetasosConfig` has `alert_max_session_contribution_entries: int = 10_000` with validation
- [ ] Cross-field validation: `alert_per_session_contribution_cap <= alert_per_minute_cap` (reject `>`, allow `==`)
- [ ] `AlertManager` tracks per-`(rule_id, session_id)` contribution counts in `_per_session_minute_timestamps`
- [ ] `AlertManager` exposes `session_rate_limited_count` property for observability
- [ ] Non-critical alert path checks memory bound, then session contribution cap, before global per-minute cap
- [ ] Memory bound rejects new sessions (rate-limits) rather than evicting live tracking entries
- [ ] Session contribution gate does not consume global cap slots when it rate-limits
- [ ] `_prune_stale` cleans session contribution deques (60s window expiry)
- [ ] `rate_limited_count` semantics unchanged (global-only); `session_rate_limited_count` is session-only
- [ ] All 12 new alerting tests pass
- [ ] 7 new config validation tests pass
- [ ] Existing tests adjusted: `test_tier3_bypasses_per_minute_cap` and `test_rate_limited_count_reflects_caps` pass `alert_per_session_contribution_cap=1` explicitly
- [ ] Critical exemption tests pass without regression
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Deferred (P2+)

- **Phantom entries from globally-rejected alerts** (edge-cases R3/F-4, P2): `setdefault` creates tracking entries even when the alert is subsequently rejected by the global per-minute/per-hour cap. These empty deques are self-healing (pruned on next `_prune_stale`), bounded by `max_entries`, and consume negligible memory. No code change needed.
- **Test 7 assertion may hit 5-key overshoot** (edge-cases R3/F-6, P2): The `test_memory_bound_rejects_new_sessions` assertion should either trigger `_prune_stale` before checking dict size, or assert `<= max_entries + 5`. Implementer should choose at test-authoring time.
- **Category (c) additions beyond brief** (conventions R3/F-1-4, P3): Config field promotion (D3), reject-not-evict (D3), `session_rate_limited_count` property, expanded test plan — all responsive to review findings with explicit rationale.

## Out of scope

- Adaptive per-session caps based on session trust score (future work — requires profile integration)
- IP-level or agent-level rate limiting (Petasos operates at session granularity, not network layer)
- Retroactive cap recalculation when a session is later identified as adversarial
- Drawbridge backport (uncoupled; own ticket if needed)
- Critical alert path rate limiting (PET-16 scope)
- Per-hour session contribution tracking (the 60s window aligns with the per-minute cap; per-hour contribution caps add complexity without proportional security gain given the per-hour global cap already exists)
