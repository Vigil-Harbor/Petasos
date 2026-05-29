# Correctness Review — Round 1

## Findings

### F-1: Spec tier_escalation severity mapping diverges from brief table
**Severity:** P2
**Where:** spec section "5 Built-in Rules", brief line 100
**Claim:** The spec defines tier_escalation severities as "warning (->tier1), high (->tier2), critical (->tier3)" with three severity levels including the none->tier1 transition.
**Why this is wrong:** The brief's table says "warning (T1->T2), high (T2->T3)" — only two transitions and different mappings. However, the brief is internally inconsistent: its rate-limiting section says "Tier 3 escalation alerts (`severity == 'critical'`) bypass all rate limiting" yet no rule in the brief's table produces a "critical" alert. The spec resolves this contradiction by adding the critical tier3 transition.
**Suggested fix:** Add a Decision box explicitly noting the brief's internal contradiction and the spec's resolution.

### F-2: Premium features manifest uses "unlocked"/"locked" instead of brief's "available"/"disabled"/"locked"
**Severity:** P2
**Where:** spec section 5 "Premium features manifest", brief line 128
**Suggested fix:** Add a Decision box explaining why two values are preferred over three, or adopt the brief's three-value scheme.

### F-3: Stale line-number reference (downgraded to P4)
**Severity:** P4

### F-4: Spec says "no new audit config needed" then adds `audit_verbosity`
**Severity:** P3
**Suggested fix:** Change scope table to mention audit_verbosity.

### F-5: Plane ticket not cached in MCP memory
**Severity:** P3

### F-6: Spec does not show wiring code from config to AuditEmitter
**Severity:** P3
**Suggested fix:** Add instantiation snippet to section 5.

### F-7: AuditEmitter.emit return value unspecified
**Severity:** P3
**Suggested fix:** Add `-> AuditEvent` return type to emit method description.

### F-8: `alert_high_severity_threshold` typed as `str` — defensible for serialization
**Severity:** P3

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 5 | P4: 1

STATUS: GREEN
