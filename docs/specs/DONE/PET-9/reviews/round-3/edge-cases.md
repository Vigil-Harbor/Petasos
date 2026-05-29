# Edge-Cases Review — Round 3

## Closure of round 2 findings

All 8 round-2 edge-case findings CLOSED (6 fixed in spec, 2 deferred in P2+ section).

## Findings

### F-1: `_SEVERITY_RANK` is private to `pipeline.py` — alerting.py import creates coupling
**Severity:** P2
**Where:** spec line 178
**Edge case:** Importing `_SEVERITY_RANK` (underscore-prefixed) from pipeline.py into alerting.py violates private-name convention and creates fragile coupling.
**Suggested fix:** Define local severity comparison in alerting.py or promote _SEVERITY_RANK to public.

### F-2: Callback exception during `evaluate()` iteration — partial alert delivery
**Severity:** P2
**Where:** spec lines 167-169, 213-215
**Edge case:** If on_alert callback raises on alert #2 of 3, alerts #3+ are never delivered. evaluate() aborts mid-iteration.
**Suggested fix:** Per-alert try/except in the callback loop; accumulate failures; raise after iteration.

### F-3: `alert_ring_buffer_capacity=0` passes "positive" validation silently
**Severity:** P2
**Where:** spec lines 254, 374
**Edge case:** deque(maxlen=0) discards all entries; rules silently become no-ops.
**Suggested fix:** The "positive" constraint covers this (>0), but add explicit test.

### F-4: `_rule_cooldowns` pruning with large cooldown_seconds
**Severity:** P3
**Where:** spec lines 207-209
**Suggested fix:** No action required — bounded by max_sessions * 5.

### F-5: `pii_volume_spike` appends zero-count entries to ring buffer
**Severity:** P3
**Where:** spec line 181
**Edge case:** Zero-PII scans fill buffer and evict meaningful entries.
**Suggested fix:** Only append when entity_count > 0.

### F-6: `cross_session_burst` ring buffer capacity starved by single high-frequency session
**Severity:** P3
**Where:** spec lines 180, 203-205
**Suggested fix:** Document capacity sizing guidance.

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 3 | P4: 0

STATUS: GREEN
