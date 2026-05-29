# Edge-Cases Review — Round 2

## Closure of round 1 findings

All 15 round-1 edge-case findings CLOSED. See closure table in review agent output.

## Findings

### F-1: `__none__` sentinel key collides with a real session_id of the same string
**Severity:** P2
**Where:** spec lines 94, 185
**Edge case:** A caller passes `session_id="__none__"` as a literal string. Both AuditEmitter sequence counter and AlertManager dedup key use `"__none__"` for None sessions, causing collision.
**Suggested fix:** Use a zero-length string `""` or private object sentinel, or use separate tracking for None sessions.

### F-2: `pii_volume_spike` ring buffer tracks timestamps but not entity counts per scan
**Severity:** P2
**Where:** spec lines 153, 178
**Edge case:** Ring buffer stores `(timestamp, session_id)` — one entry per evaluate() call. PII volume threshold requires accumulating entity counts across the window, not just scan counts.
**Suggested fix:** Specify that pii_volume_spike uses a deque of `(timestamp, entity_count)` tuples and sums counts within the window.

### F-3: `alert_high_severity_threshold` Literal string vs Severity enum comparison mechanism unspecified
**Severity:** P2
**Where:** spec lines 175, 244, 355
**Edge case:** Config field is a Literal string; ScanFinding.severity is a Severity enum. "At or above" comparison requires explicit conversion and ordering semantics.
**Suggested fix:** Specify comparison uses Severity enum ordinal with `Severity(config_value)` conversion.

### F-4: AuditEmitter `_last_emit_time` clock choice unspecified
**Severity:** P2
**Where:** spec lines 206-208, 231-233
**Edge case:** The spec does not specify which clock _last_emit_time uses for TTL pruning.
**Suggested fix:** Specify `time.monotonic()` to match FrequencyTracker pattern.

### F-5: `evaluate()` return value ambiguity — survivors only or all candidates?
**Severity:** P2
**Where:** spec lines 159-166
**Edge case:** "Returns the list" is ambiguous about whether rate-limited/suppressed alerts are included.
**Suggested fix:** Clarify that evaluate() returns only alerts that survived rate limiting (same set as on_alert invocations).

### F-6: `rapid_fire` ring buffer keyed per-rule but needs per-session-per-rule tracking
**Severity:** P2
**Where:** spec lines 153, 176
**Edge case:** Shared ring buffer capacity across all sessions means individual session entries can be evicted before reaching threshold N under high fan-out.
**Suggested fix:** Key ring buffer as `rule_id|session_id` for rapid_fire, or document capacity sizing requirement.

### F-7: Alert hook return value discarded — alerts not on PipelineResult
**Severity:** P3
**Where:** spec lines 279-282
**Suggested fix:** Document that alerts are callback-only and not part of PipelineResult.

### F-8: `tier_escalation` fires on every new session's first flagged scan (none->tier1)
**Severity:** P3
**Where:** spec lines 174, 436-437
**Suggested fix:** Document this as expected behavior and note rate-limiting interaction.

## Summary
P0: 0 | P1: 0 | P2: 6 | P3: 2 | P4: 0

STATUS: GREEN
