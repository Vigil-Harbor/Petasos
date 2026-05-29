# Edge-Cases Review — Round 1

## Findings

### F-1: `tier_escalation` rule uses `evaluate_tier(previous_score)` but `previous_score` is the decayed score
**Severity:** P1
**Where:** spec section "5 Built-in Rules" rule 1
**Edge case:** FrequencyUpdateResult.previous_score is the decayed value (frequency.py line 147). A session at tier1 that decays below the threshold and re-triggers would fire a spurious none->tier1 escalation alert.
**Suggested fix:** Either document this as acceptable behavior or store previous tier in FrequencyUpdateResult.

### F-2: Unbounded growth of `_sequence_counters` dict — no eviction
**Severity:** P2
**Where:** spec section 3 AuditEmitter
**Suggested fix:** Add eviction strategy or document memory bound.

### F-3: `_per_minute_timestamps` and `_per_hour_timestamps` dict keys grow unboundedly
**Severity:** P2
**Suggested fix:** Prune empty deques from the parent dict during evaluate.

### F-4: `_rule_cooldowns` dict grows unboundedly
**Severity:** P2
**Suggested fix:** Prune expired entries periodically.

### F-5: `session_id=None` shared across all null-session scans for alert rules
**Severity:** P1
**Where:** spec section 4 AlertManager rules
**Edge case:** rapid_fire would trigger for ALL null-session scans combined. cross_session_burst would count None as exactly 1 session. Dedup key would share cooldown.
**Suggested fix:** Specify that rapid_fire and cross_session_burst skip when session_id=None.

### F-6: `tier_escalation` rule pseudocode omits config argument to `evaluate_tier()`
**Severity:** P1
**Where:** spec section "5 Built-in Rules" rule 1
**Suggested fix:** Amend to `evaluate_tier(previous_score, self._config)`.

### F-7: Callback exception wrapping — standalone use gets unexpected RuntimeError
**Severity:** P2
**Suggested fix:** Document that emit() can raise when used standalone.

### F-8: Audit hook receives PipelineResult that may be replaced later
**Severity:** P2
**Suggested fix:** Document ordering: audit captures result state before alert hook runs.

### F-9: `pii_volume_spike` — how are PII entities counted?
**Severity:** P2
**Suggested fix:** Define PII entity count as findings where finding_type == "pii".

### F-10: `cross_session_burst` — None session distinctness undefined
**Severity:** P2
**Suggested fix:** Specify None-session exclusion from cross_session_burst.

### F-11: `time.monotonic()` platform behavior during suspend
**Severity:** P3

### F-12: Sequence counter integer overflow
**Severity:** P4

### F-13: `alert_high_severity_threshold` case sensitivity
**Severity:** P2
**Suggested fix:** Specify validation via Severity(value).

### F-14: `freq_result=None` when frequency disabled — correct degradation
**Severity:** P3

### F-15: Ring buffer capacity vs rule threshold misconfiguration
**Severity:** P3
**Suggested fix:** Add validation that rule counts <= ring buffer capacity.

## Summary
P0: 0 | P1: 3 | P2: 7 | P3: 3 | P4: 1

STATUS: RED P0=0 P1=3 P2=7 P3=3 P4=1
