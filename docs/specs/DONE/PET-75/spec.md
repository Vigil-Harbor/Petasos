# PET-75: Frequency + Escalation Hardening

**Ticket:** PET-75 · **Parent:** PET-14 · **Blocks:** PET-12
**Child findings:** ESC-01 (PET-28), ESC-03 (PET-29), FREQ-04 (PET-32), FREQ-05 (PET-33)

## Goal

Harden the frequency tracking and escalation subsystem against four red-team findings: restore the Tier 3 "cannot be disabled" invariant when frequency is off (ESC-01), eliminate the duplicate tier-derivation code path (ESC-03), make rate-limited responses distinguishable from disabled responses (FREQ-04), and replace the O(n) TTL eviction scan with O(k) amortized eviction (FREQ-05).

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/premium/escalation.py` | Add `derive_tier()` shared helper (ESC-03) |
| `petasos/premium/frequency.py` | Add `rate_limited` field to `FrequencyUpdateResult`; replace O(n) TTL scan with deque-based eviction + compaction (FREQ-04, FREQ-05); update `RATE_LIMITED_RESULT` sentinel |
| `petasos/premium/guard.py` | Refactor `_derive_tier()` to use shared `derive_tier()` (ESC-03) |
| `petasos/premium/__init__.py` | Re-export `derive_tier` (ESC-03) |
| `petasos/pipeline.py` | Add `_standalone_tier3_check()` after Stage 5 merge, before profile hooks; add rate-limited logging in `_premium_frequency_hook` (ESC-01, FREQ-04) |
| `tests/test_frequency.py` | Update `test_rate_limited_result_is_frozen` to assert `rate_limited is True` (FREQ-04) |
| `tests/adversarial/escalation/__init__.py` | New empty package init |
| `tests/adversarial/escalation/test_standalone_tier3.py` | New: 5 tests for ESC-01 |
| `tests/adversarial/escalation/test_derive_tier.py` | New: 4 tests for ESC-03 |
| `tests/adversarial/frequency/test_rate_limited_sentinel.py` | New: 4 tests for FREQ-04 |
| `tests/adversarial/frequency/test_ttl_eviction.py` | New: 4 tests for FREQ-05 |

### Files to leave alone

- `petasos/config.py` — no config changes; the standalone tier-3 check uses a hardcoded critical-finding count floor
- `petasos/premium/audit.py` — no audit changes
- `petasos/premium/alerting.py` — no alerting changes
- `petasos/premium/license.py` — no license changes
- `petasos/scanners/minimal.py` — no scanner changes

## Decisions

### Decision 1: Standalone tier-3 check is a safety net, not a replacement

ESC-01 asks "should Tier 3 be a frequency-derived property or a static finding-count threshold?" Answer: both. The frequency-based Tier 3 remains the primary mechanism (score accumulates over time via exponential decay). The standalone check is a *floor* — if a single `inspect()` call produces >= 3 CRITICAL-severity findings, force `escalation_tier="tier3"` and `safe=False` regardless of premium/frequency state. This preserves the "Tier 3 cannot be disabled" invariant documented in CLAUDE.md.

The count threshold (3) is hardcoded as `_STANDALONE_TIER3_CRITICAL_COUNT = 3`. It is not configurable — this is the safety net, not a tuning knob. The brief says "configurable, default 3" but this spec deliberately hardcodes it: a configurable safety net can be configured away. The frequency-based tier3 is the configurable mechanism; this is the invariant floor.

### Decision 2: `derive_tier()` accepts explicit thresholds, not a config object

ESC-03 proposes extracting `derive_tier(score, config)`. The `guard.py` call site uses profile-specific thresholds, not config thresholds. If we pass a config object, the guard still needs a separate path for profiles. Instead: `derive_tier(score: float, tier1: float, tier2: float, tier3: float) -> str`. Both `evaluate_tier()` and `guard._derive_tier()` call it with their respective threshold source.

### Decision 3: Deque over heap for TTL eviction, with compaction trigger

FREQ-05 proposes heap or deque. All sessions share a single `session_ttl_seconds`, so insertion order equals expiry order. A `deque[tuple[float, str]]` of `(expiry_time, session_id)` is sufficient.

**Tradeoff:** Each session update appends a new deque entry; stale entries accumulate until they reach the front and expire. For long-lived sessions updated frequently, the deque can grow to `max_sessions * (TTL / avg_update_interval)` entries. To bound this, add a compaction trigger: when `len(self._ttl_deque) > 2 * self._max_sessions`, rebuild the deque from live sessions only.

### Decision 4: `rate_limited` is a boolean field only — tier stays `"none"`

FREQ-04 needs to distinguish rate-limited from disabled. Adding `rate_limited: bool = True` to `FrequencyUpdateResult` is sufficient. The `tier` field stays `"none"` on `RATE_LIMITED_RESULT` — introducing a novel tier string like `"rate_limited"` would break the implicit closed vocabulary (`"none"`, `"tier1"`, `"tier2"`, `"tier3"`) used by `_TIER_ACTIONS` (escalation.py:11-16), `evaluate_escalation()`, alerting severity maps, and audit trail schemas. Callers distinguish via `result.rate_limited`.

## Design

### ESC-01: Standalone tier-3 check in pipeline

In `petasos/pipeline.py`, add a module-level constant and a helper:

```python
_STANDALONE_TIER3_CRITICAL_COUNT = 3

def _standalone_tier3_check(findings: tuple[ScanFinding, ...]) -> bool:
    critical_count = sum(1 for f in findings if f.severity == Severity.CRITICAL)
    return critical_count >= _STANDALONE_TIER3_CRITICAL_COUNT
```

In `_inspect_inner()`, immediately after Stage 5 merge (line 418, `merged = merge_findings(all_results)`) and **before** Stage 5b (confidence floor filtering) and Stage 5c (severity overrides):

```python
# Stage 5a: Standalone tier-3 safety net (ESC-01)
# Runs on pre-filter merged findings so neither confidence-floor filtering (5b)
# nor severity overrides (5c) can suppress the CRITICAL count.
standalone_tier3 = _standalone_tier3_check(merged)
```

Then after Stage 8 (fail-mode enforcement, line 469), apply the result:

```python
# Stage 8b: Apply standalone tier-3 if triggered
if standalone_tier3:
    safe = False
    if escalation_tier != "tier3":
        escalation_tier = "tier3"
```

Splitting the check (Stage 5a) from the application (Stage 8b) ensures the CRITICAL count is evaluated on raw merged output before any profile manipulation, while the tier/safe override happens in the correct position relative to fail-mode enforcement.

If the frequency subsystem already computed tier3, the `escalation_tier != "tier3"` guard is false and the assignment is skipped (idempotent). If the frequency subsystem computed tier1 or tier2, the standalone check overrides to tier3 since the critical-count floor takes precedence.

### ESC-03: Shared `derive_tier()` helper

In `petasos/premium/escalation.py`, add before `evaluate_tier()`:

```python
def derive_tier(score: float, tier1: float, tier2: float, tier3: float) -> str:
    if not math.isfinite(score):
        return "tier3"
    if score >= tier3:
        return "tier3"
    if score >= tier2:
        return "tier2"
    if score >= tier1:
        return "tier1"
    return "none"
```

The `math.isfinite` guard returns `"tier3"` for NaN/Inf scores — fail-closed in a security context. This is new behavior (the old `evaluate_tier` would return `"none"` for NaN), but is the correct defensive choice. Add `import math` at the top of the file.

Refactor `evaluate_tier()` to delegate:

```python
def evaluate_tier(score: float, config: PetasosConfig) -> str:
    return derive_tier(score, config.tier1_threshold, config.tier2_threshold, config.tier3_threshold)
```

In `petasos/premium/guard.py`, refactor `_derive_tier()` (lines 187–206). Replace the profile-override branch (lines 197–205) with a single `derive_tier()` call:

```python
def _derive_tier(self, session_id: str) -> str:
    if self._frequency_tracker.is_terminated(session_id):
        return "tier3"
    if self._config.session_secret is not None:
        token = self._frequency_tracker.mint_token(session_id, self._pipeline.host_id)
        state = self._frequency_tracker.get_state(token)
    else:
        state = self._frequency_tracker.get_state(session_id)
    if state is None:
        return "none"
    if self._profile and self._profile.tier_thresholds:
        t = self._profile.tier_thresholds
        return derive_tier(state.last_score, t.tier1, t.tier2, t.tier3)
    return evaluate_tier(state.last_score, self._config)
```

Update the import in `guard.py` to include `derive_tier`:

```python
from petasos.premium.escalation import derive_tier, evaluate_tier
```

In `petasos/premium/__init__.py`, add `derive_tier` to the import and `__all__`:

```python
from petasos.premium.escalation import (
    TIER3_FLOOR,
    EscalationResult,
    derive_tier,
    evaluate_escalation,
    evaluate_tier,
)
```

### FREQ-04: Distinct `RATE_LIMITED_RESULT`

In `petasos/premium/frequency.py`, modify `FrequencyUpdateResult`:

```python
@dataclass(frozen=True)
class FrequencyUpdateResult:
    previous_score: float
    current_score: float
    tier: str
    terminated: bool
    rate_limited: bool = False
```

Update the sentinels — `RATE_LIMITED_RESULT` keeps `tier="none"` but gains `rate_limited=True`:

```python
DISABLED_RESULT = FrequencyUpdateResult(
    previous_score=0.0, current_score=0.0, tier="none", terminated=False
)
RATE_LIMITED_RESULT = FrequencyUpdateResult(
    previous_score=0.0, current_score=0.0, tier="none", terminated=False, rate_limited=True
)
```

No changes needed to `update()` — it already returns `RATE_LIMITED_RESULT` at line 178.

In `petasos/pipeline.py`, add logging in `_premium_frequency_hook` to distinguish rate-limited from disabled:

```python
async def _premium_frequency_hook(
    self, findings: tuple[ScanFinding, ...], session_id: str | None
) -> FrequencyUpdateResult | None:
    if not self._check_premium("frequency"):
        return None
    if not self._config.frequency_enabled:
        return None
    if session_id is None:
        return None
    rule_ids = [f.rule_id for f in findings]
    if self._config.session_secret is not None:
        token = self._frequency_tracker.mint_token(session_id, self._host_id)
        result = self._frequency_tracker.update(token, rule_ids)
    else:
        result = self._frequency_tracker.update(session_id, rule_ids)
    if result.rate_limited:
        _logger.info("session %s rate-limited (frequency cap reached)", session_id)
    return result
```

In `tests/test_frequency.py`, update `test_rate_limited_result_is_frozen`:

```python
def test_rate_limited_result_is_frozen(self) -> None:
    assert RATE_LIMITED_RESULT.current_score == 0.0
    assert RATE_LIMITED_RESULT.tier == "none"
    assert RATE_LIMITED_RESULT.terminated is False
    assert RATE_LIMITED_RESULT.rate_limited is True
```

And update `test_disabled_result_is_frozen`:

```python
def test_disabled_result_is_frozen(self) -> None:
    assert DISABLED_RESULT.current_score == 0.0
    assert DISABLED_RESULT.tier == "none"
    assert DISABLED_RESULT.terminated is False
    assert DISABLED_RESULT.rate_limited is False
```

### FREQ-05: O(k) TTL eviction via sorted deque with compaction

In `petasos/premium/frequency.py`, add a TTL deque to `FrequencyTracker.__init__()`:

```python
self._ttl_deque: deque[tuple[float, str]] = deque()
```

When a session is created (Step 2, line 180-183), append to the deque:

```python
expiry = now + self._session_ttl
self._ttl_deque.append((expiry, session_id))
```

When a session is updated (Step 10, line 228-229), append a new expiry entry:

```python
new_expiry = now + self._session_ttl
self._ttl_deque.append((new_expiry, session_id))
```

Replace Step 1 (lines 142-153) with deque-based eviction:

```python
# Step 1: Passive TTL eviction (O(k) amortized via sorted deque)
while self._ttl_deque and self._ttl_deque[0][0] <= now:
    _, sid = self._ttl_deque.popleft()
    if sid not in self._sessions:
        continue
    state = self._sessions[sid]
    if state.last_update + self._session_ttl > now:
        continue  # session was refreshed — this deque entry is stale
    if state.terminated and sid not in self._terminated_ids:
        self._terminated_ids[sid] = None
        self._enforce_tombstone_cap()
    del self._sessions[sid]

# Step 1b: Deque compaction (prevents unbounded growth from refreshed sessions)
if len(self._ttl_deque) > 2 * self._max_sessions:
    self._compact_ttl_deque(now)
```

Add the compaction helper:

```python
def _compact_ttl_deque(self, now: float) -> None:
    entries: list[tuple[float, str]] = []
    for sid, state in self._sessions.items():
        expiry = state.last_update + self._session_ttl
        if expiry > now:
            entries.append((expiry, sid))
    entries.sort()
    self._ttl_deque = deque(entries)
```

This rebuilds the deque from live sessions only, dropping all stale entries, and sorts by expiry time to preserve the monotonic-expiry invariant that the eviction loop depends on (dict iteration order is insertion order, not `last_update` order). Cost is O(n log n) where n = live sessions — bounded by `max_sessions`. Triggers when deque has > 2x more entries than `max_sessions`, amortizing the cost.

Update `clear()` to reset the deque:

```python
def clear(self) -> None:
    self._sessions.clear()
    self._creation_timestamps.clear()
    self._terminated_ids.clear()
    self._ttl_deque.clear()
```

Note: `reset()` and `force_reset()` leave stale deque entries for the removed session. These entries are benign — they hit the `sid not in self._sessions: continue` check at eviction time and are discarded. The compaction trigger prevents long-term accumulation.

## Test plan

### ESC-01 tests (`tests/adversarial/escalation/test_standalone_tier3.py`)

1. **`test_tier3_fires_without_frequency`**: `frequency_enabled=False`, inject 3+ CRITICAL findings via MinimalScanner, assert `escalation_tier="tier3"` and `safe=False`
2. **`test_tier3_fires_without_premium`**: No license activated, inject 3+ CRITICAL findings, assert `escalation_tier="tier3"` and `safe=False`
3. **`test_below_threshold_no_tier3`**: License active, `frequency_enabled=False`, 2 CRITICAL findings → `escalation_tier` is None (not tier3), `safe` is False (from fail-mode). Proves the threshold boundary: 2 < 3 does not trigger standalone check. Must use premium-active path so `escalation_tier=None` is meaningful (not just the premium-inactive default).
4. **`test_standalone_idempotent_with_frequency`**: frequency on, score triggers tier3, standalone also fires → `escalation_tier="tier3"` exactly once
5. **`test_standalone_survives_severity_override`**: License active, `frequency_enabled=False`, profile with `severity_overrides` that downgrades the 3 CRITICAL findings to HIGH. Assert `escalation_tier="tier3"` and `safe=False` still fire, proving the standalone check ran before severity overrides.

### ESC-03 tests (`tests/adversarial/escalation/test_derive_tier.py`)

5. **`test_derive_tier_boundaries`**: Call `derive_tier()` at exact boundary values (tier1-1, tier1, tier2-1, tier2, tier3-1, tier3), verify all 4 tier returns
6. **`test_derive_tier_nan_fails_closed`**: `derive_tier(float('nan'), ...)` returns `"tier3"`
7. **`test_guard_with_profile_thresholds_returns_correct_tier`**: ToolCallGuard with profile tier_thresholds differing from config, verify correct tier for a score that would be tier1 under config but tier2 under profile
8. **`test_guard_without_profile_falls_back_to_config`**: ToolCallGuard without profile, verify tier matches `evaluate_tier()` result

### FREQ-04 tests (`tests/adversarial/frequency/test_rate_limited_sentinel.py`)

9. **`test_rate_limited_distinct_from_disabled`**: `RATE_LIMITED_RESULT.rate_limited is True`, `DISABLED_RESULT.rate_limited is False`; both have `tier == "none"`
10. **`test_rate_limited_result_fields`**: `RATE_LIMITED_RESULT.tier == "none"`, `.rate_limited is True`, `.terminated is False`
11. **`test_disabled_result_fields`**: `DISABLED_RESULT.tier == "none"`, `.rate_limited is False`, `.terminated is False`
12. **`test_update_returns_rate_limited_at_cap`**: Fill sessions to `max_sessions`, flood creation timestamps, assert returned result has `rate_limited is True`

### FREQ-05 tests (`tests/adversarial/frequency/test_ttl_eviction.py`)

13. **`test_ttl_eviction_uses_deque`**: Create 100 sessions, advance time past TTL, call `update()` — verify all expired sessions evicted
14. **`test_refreshed_session_survives_stale_deque_entry`**: Create session, update it (refreshes TTL), advance past original TTL but not refreshed TTL — session survives
15. **`test_compaction_triggers_at_threshold`**: Create sessions, update each multiple times to inflate deque, verify compaction fires when deque exceeds `2 * max_sessions`, trims to live-session count, and entries are sorted by expiry time
16. **`test_clear_resets_deque`**: Call `clear()`, assert `_ttl_deque` is empty

## Test command

```bash
python -m pytest tests/adversarial/escalation/ tests/adversarial/frequency/ tests/test_frequency.py tests/test_pipeline.py -v && ruff check . && mypy --strict .
```

## Done when

- [ ] `_standalone_tier3_check()` fires when >= 3 CRITICAL findings, regardless of premium/frequency state
- [ ] Standalone check evaluates on pre-severity-override merged findings
- [ ] With `frequency_enabled=False`, a session with >= 3 CRITICAL findings gets `escalation_tier="tier3"` and `safe=False`
- [ ] `derive_tier()` is a single shared function in `escalation.py`, exported via `premium/__init__.py`
- [ ] `derive_tier()` returns `"tier3"` for NaN/Inf scores (fail-closed)
- [ ] `evaluate_tier()` delegates to `derive_tier()`
- [ ] `guard._derive_tier()` profile path uses `derive_tier()` instead of inline threshold comparison
- [ ] `RATE_LIMITED_RESULT.tier == "none"` and `RATE_LIMITED_RESULT.rate_limited is True`
- [ ] `DISABLED_RESULT.tier == "none"` and `DISABLED_RESULT.rate_limited is False`
- [ ] Pipeline logs `"session {sid} rate-limited"` when rate limiting kicks in
- [ ] TTL eviction in `update()` uses deque-based O(k) scan, not O(n) full iteration
- [ ] Deque compaction triggers when `len(deque) > 2 * max_sessions`, rebuilding from live sessions
- [ ] Refreshed sessions survive stale deque entries
- [ ] >= 17 tests across all 4 findings (5 ESC-01 + 4 ESC-03 + 4 FREQ-04 + 4 FREQ-05)
- [ ] `mypy --strict` clean, `ruff check .` clean
- [ ] Existing frequency and escalation tests still pass (including updated `test_rate_limited_result_is_frozen`)

## Out of scope

- Per-session variable TTL (all sessions share config-level TTL today)
- Distributed frequency tracking (single-process only)
- PET-50 (PIPE-03 scanner timeout / circuit breaker) — related but separate brief
- Config changes (no new config fields — standalone tier-3 threshold is hardcoded as a policy floor)
- Performance benchmark test (10k sessions < 1ms) — behavior is covered by functional tests; benchmarking belongs in a separate suite
