# Edge-Cases Review — PET-16 Round 1

## Findings

### F-1: Unbounded deque per rule_id — no maxlen on critical deques (P2)
**Where:** spec.md:105-107 (Design section 2b)
**Issue:** Deques created via `deque()` with no `maxlen`. In practice bounded to `cap` entries per key. Consistent with existing non-critical deque pattern.
**Suggested fix:** No spec change — consistent with existing code.

### F-2: Test 3 cannot exercise per-rule_id isolation with production code (P2)
**Where:** spec.md:171, 187
**Issue:** Only `tier_escalation` produces critical alerts. Whitebox dict inspection is pragmatic but tests data structure, not behavioral invariant.
**Suggested fix:** Acknowledge as structural test or inject synthetic critical alert via monkeypatch.

### F-3: Thread safety — evaluate is not thread-safe (P2)
**Where:** spec.md:103-134
**Issue:** Pre-existing condition. TOCTOU race on cap check + append. Pipeline uses single asyncio event loop.
**Suggested fix:** Add note to Out of scope: "Thread safety of AlertManager.evaluate — existing code is single-threaded."

### F-4: on_alert callback exception consumes critical budget (P2)
**Where:** spec.md:103-134 referencing alerting.py L125-129
**Issue:** `crit_deque.append(now)` happens before callback. If callback raises, budget consumed but alert lost. Matches non-critical pattern.
**Suggested fix:** Document as accepted behavior.

### F-5: _evict_old boundary — exactly-60s entries survive (P3)
**Where:** spec.md:108-109
**Issue:** Strict greater-than in `_evict_old`. Pre-existing, consistent.

### F-6: Config validation insertion point line reference (P3)
**Where:** spec.md:65
**Issue:** "Around L170" is accurate enough; spec guidance is sufficient.

### F-7: Config validation tests not in Done-when (P3)
**Where:** spec.md:199-204
**Issue:** Three config tests proposed but not in acceptance criteria.

### F-8: No test for _prune_stale cleaning critical deques (P2)
**Where:** spec.md:142-156, 179-197
**Issue:** Done-when requires "_prune_stale cleans critical cap deques" but no test verifies dict key removal.
**Suggested fix:** Add a 7th test for prune_stale dict key cleanup.

### F-9: Test 5 framing inconsistency (P3)
**Where:** spec.md:168, 175-176 vs 191-192
**Issue:** "Meta-test" framing vs actual new test. Test plan body is authoritative.

### F-10: Memory growth under sustained attack — bounded by design (P3)
**Where:** spec.md:87-88, 142-156
**Issue:** O(num_rules * cap) — negligible. No change needed.

## Summary
P0: 0 | P1: 0 | P2: 4 | P3: 4 | P4: 0

STATUS: GREEN
