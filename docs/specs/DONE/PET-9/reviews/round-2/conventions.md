# Conventions Review — Round 2

## Closure of round 1 findings

All 8 round-1 conventions findings CLOSED. See closure table in review agent output.

## Findings

### F-1: Feature gate key `"alerting"` does not follow `<key>_enabled` naming convention
**Severity:** P4
**Where:** spec line 299
**Convention violated:** Existing _FEATURE_GATES naming pattern
**Evidence:** Pattern is `<key>_enabled`: frequency/frequency_enabled, escalation/escalation_enabled, tool_guard/tool_guard_enabled. New: audit/audit_enabled (consistent), but alerting/alert_enabled (breaks pattern). Inherited from pre-existing config field.
**Suggested fix:** No action — inherited from PET-6.

### F-2: Brief specifies three-value premium manifest; spec uses existing two-value without Decision section
**Severity:** P3
**Where:** spec lines 306-307
**Suggested fix:** Add brief note acknowledging deviation from brief line 128.

### F-3: `on_audit`/`on_alert` params on Pipeline.__init__() — spec-level addition with rationale
**Severity:** P3
**Where:** spec lines 316-329, Decision at lines 342-344
**Suggested fix:** None required. Surfacing for visibility.

### F-4: `AuditEmitter._last_emit_time` dict not listed in internal state section
**Severity:** P4
**Where:** spec line 208
**Suggested fix:** Add to internal state description near line 94.

### F-5: tier_escalation none->tier1 addition — authorized spec-level addition
**Severity:** P3
**Where:** spec lines 173-174, Decision at lines 227-229
**Suggested fix:** None required. Surfacing for visibility.

### F-6: Drawbridge out-of-band audit emission decision — alignment confirmed
**Severity:** P4
**Suggested fix:** None.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 3 | P4: 3

STATUS: GREEN
