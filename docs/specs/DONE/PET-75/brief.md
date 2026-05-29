# PET-75: Frequency + Escalation Hardening

**Plane items:** PET-28 (ESC-01), PET-29 (ESC-03), PET-32 (FREQ-04), PET-33 (FREQ-05)
**Files touched:** `petasos/premium/frequency.py`, `petasos/premium/escalation.py`, `tests/adversarial/frequency/`, `tests/adversarial/escalation/`
**Priority:** medium (ESC-01, FREQ-04); low (ESC-03, FREQ-05)
**Parent:** PET-14 (red-team security review)
**Blocks:** PET-12 (release)

## Findings

| ID | Severity | Attack | Current behavior | Remediation |
|----|----------|--------|------------------|-------------|
| ESC-01 | medium | Disable `frequency_enabled` in config | Tier 3 escalation doesn't fire when frequency subsystem is off — the "cannot be disabled" invariant only holds when the subsystem is active | Default `frequency_enabled=True` for security profiles; add a standalone tier-3 check in pipeline that evaluates even when frequency is off, or document that Tier 3 requires frequency |
| ESC-03 | low | `evaluate_tier()` and `guard._derive_tier()` use same logic | Two independent tier-derivation sites risk drift if thresholds change | Extract `derive_tier(score, config) -> str` as a shared helper in `escalation.py`; both callers use it |
| FREQ-04 | medium | Flood new sessions at cap → `RATE_LIMITED_RESULT` equals `DISABLED` | `RATE_LIMITED_RESULT` (score=0, tier="none") is indistinguishable from `DISABLED_RESULT` — callers can't tell if rate limiting kicked in or premium is off | Add distinct sentinel: `RATE_LIMITED_RESULT` with `tier="rate_limited"` and a flag; pipeline logs the distinction |
| FREQ-05 | low | 10k sessions update loop | Step 1 TTL eviction is O(n) — iterates all sessions every `update()` call | Batch eviction: maintain a TTL-sorted deque of `(expiry, session_id)` pairs; pop expired entries from the front instead of scanning all sessions |

## Approach

1. **ESC-01:** The invariant "Tier 3 cannot be disabled" is documented as hardcoded. But if `frequency_enabled=False`, the frequency hook is a no-op and no tier is ever computed. Fix: add a `_standalone_tier3_check(findings)` in pipeline that runs regardless of premium/frequency state. If any scan produces >= N critical findings in a session (configurable, default 3), force `escalation_tier="tier3"` and `safe=False`. This preserves the invariant without requiring the full frequency subsystem.

2. **ESC-03:** Extract `derive_tier(score: float, tier1: float, tier2: float, tier3: float) -> str` into `escalation.py`. Update `evaluate_tier()` and `guard._derive_tier()` to call it. Single source of truth.

3. **FREQ-04:** Change `RATE_LIMITED_RESULT` to use `tier="rate_limited"` (not `"none"`). Add a `rate_limited: bool = False` field to `FrequencyUpdateResult`. Pipeline can now distinguish rate-limited from disabled.

4. **FREQ-05:** Replace the O(n) TTL scan in `update()` Step 1 (lines 143-153) with a min-heap or sorted deque of `(expiry_time, session_id)`. On each `update()`, pop entries where `expiry_time < now`. This is O(k) where k is the number of expired sessions, not O(n) total.

## Decisions carried forward

- **ESC-01 standalone check:** This is a *policy decision*: should Tier 3 be a frequency-derived property or a static finding-count threshold? Decision: both. Frequency-based Tier 3 remains the primary mechanism. The standalone check is a safety net — it fires only on extreme finding counts, not on accumulation over time. The two are complementary, not redundant.
- **FREQ-05 heap vs. deque:** A `heapq` is simpler for variable-TTL sessions. If all sessions share the same TTL (current behavior), a deque sorted by insertion time is sufficient and avoids heap overhead. Current code uses a single `session_ttl_seconds` for all sessions -> deque is appropriate.

## Done when

- [ ] With `frequency_enabled=False`, a session with >= 3 CRITICAL findings still gets `escalation_tier="tier3"` and `safe=False`
- [ ] `evaluate_tier()` and `guard._derive_tier()` both call the shared `derive_tier()` helper
- [ ] `RATE_LIMITED_RESULT.tier == "rate_limited"` and `RATE_LIMITED_RESULT.rate_limited is True`
- [ ] Pipeline log output distinguishes rate-limited from disabled
- [ ] TTL eviction does not iterate all sessions — benchmark: 10k sessions, `update()` < 1ms
- [ ] >= 16 tests (4 per finding)
- [ ] `mypy --strict` clean

## Out of scope

- Per-session variable TTL (all sessions share config-level TTL today)
- Distributed frequency tracking (single-process only)
- PET-50 (PIPE-03 scanner timeout / circuit breaker) — related but separate brief
