# PET-30 Edge-Cases Review — Round 2

## Closure of round 1 findings
All 4 targeted findings (F-1 P1, F-2 P1, F-4 P2, F-7 P2) confirmed CLOSED in the revised spec.

## Findings

### F-1: `update()` tombstone early-return reports `current_score=0.0` — misleading
**Severity:** P2
The tombstone set stores `None` values, so the true score is lost at eviction time. The early-return reports `0.0` which could mislead downstream consumers. Document `0.0` as sentinel.

### F-2: No test verifies `update()` with non-empty `rule_ids` on tombstoned session returns zero score
**Severity:** P2
Test 6 should pass non-empty rule_ids and assert `current_score == 0.0`.

### F-3: `_evict_one()` defensive `_add_tombstone` refreshes FIFO position of already-tombstoned sessions
**Severity:** P3
Use conditional write (skip if already tombstoned) to preserve original FIFO position.

### F-4: `clear()` retains `_creation_timestamps.clear()` — correct, noting for completeness
**Severity:** P3 (informational)

### F-5: `max_terminated_tombstones=1` — acknowledged in Deferred section
**Severity:** P3 (informational)

### F-6: `_enforce_tombstone_cap` drops tombstones silently — no logging
**Severity:** P3
Tombstone eviction under cap pressure degrades security posture. A `_logger.info` would aid forensics.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 4 | P4: 0

STATUS: GREEN
