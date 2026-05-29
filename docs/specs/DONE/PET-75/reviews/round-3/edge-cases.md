# Edge-Cases Review — PET-75 Round 3

## Closure of round 2 findings
All round 2 findings CLOSED. Compaction sorted, test 3 meaningful, test 5 added, Stage 5a comment complete, test 15 verifies sort order.

## Findings

### F-1: Audit payload reads escalation_tier from freq_result, not result — standalone tier3 invisible to audit
**Severity:** P2
When standalone tier3 fires with freq_result=None, audit records escalation_tier=None despite PipelineResult having "tier3".

### F-2: Alerting silent on standalone tier3 events
**Severity:** P2
_check_tier_escalation returns None when freq_result is None. No alert for the safety-net scenario.

### F-3: Interleaved session updates produce out-of-order deque entries between compactions
**Severity:** P2
Sessions updated at different times may create out-of-order entries. Expired sessions behind non-expired front entries linger until compaction. Bounded by compaction trigger, no security impact.

### F-4: Test plan does not cover derive_tier with positive/negative infinity
**Severity:** P3
Test 6 only tests NaN. -Inf is the important case (only the isfinite guard covers it).

### F-5: Stage 8b placement relies on line-number precision
**Severity:** P3
If placed after _build_result instead of after Stage 8, standalone values would be stale.

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 2 | P4: 0

STATUS: GREEN
