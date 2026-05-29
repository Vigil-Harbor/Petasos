# Correctness Review — Round 2

## Closure of round 1 findings

| Lens | ID | Title | Status |
|---|---|---|---|
| correctness | F-1 | tier_escalation severity mapping diverges from brief | CLOSED |
| correctness | F-2 | Premium features manifest two-value vs three-value | PARTIAL |
| correctness | F-3 | Stale line-number reference | CLOSED (P4) |
| correctness | F-4 | Spec says "no new audit config" then adds audit_verbosity | CLOSED |
| correctness | F-5 | Plane ticket not cached in MCP memory | CLOSED (P3) |
| correctness | F-6 | Spec does not show wiring code | CLOSED |
| correctness | F-7 | AuditEmitter.emit return value unspecified | CLOSED |
| correctness | F-8 | alert_high_severity_threshold typed as str | CLOSED |

## Findings

### F-1: `AlertManager.evaluate()` signature missing `session_id` parameter
**Severity:** P0
**Where:** spec lines 158-163 (evaluate signature) vs lines 150-153, 174, 176-177, 180-187 (session-dependent behavior)
**Claim:** The spec declares `evaluate(self, result: PipelineResult, freq_result: FrequencyUpdateResult | None) -> list[Alert]` with only `result` and `freq_result` parameters.
**Why this is wrong:** The `evaluate` method needs `session_id` to implement at least 4 of its specified behaviors: (1) `rapid_fire` checks per-session scan counts and skips when `session_id is None`; (2) `cross_session_burst` excludes None sessions and tracks distinct session IDs; (3) dedup key construction uses `rule_id|session_id`; (4) every `Alert` dataclass has a `session_id` field. `PipelineResult` does not carry `session_id` (`_types.py:119-131`).
**Suggested fix:** Add `session_id: str | None` to the `evaluate` method signature.

### F-2: Brief's three-value premium features manifest still unaddressed
**Severity:** P2
**Where:** spec lines 306-307, brief line 128
**Suggested fix:** Add a Decision section explaining that the existing two-value codebase convention is preferred.

### F-3: Plane ticket not cached in MCP memory
**Severity:** P3

## Summary
P0: 1 | P1: 0 | P2: 1 | P3: 1 | P4: 0

STATUS: RED P0=1 P1=0 P2=1 P3=1 P4=0
