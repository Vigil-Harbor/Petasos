# Conventions Review — PET-75 Round 3

## Closure of round 2 findings
All round 2 findings CLOSED. Compaction sorted, test plan updated, scope table corrected.

## Findings

### F-1: Redundant frequency_enabled check in _premium_frequency_hook
**Severity:** P2
_check_premium("frequency") already gates on frequency_enabled via _FEATURE_GATES. Inherited from existing code.

### F-2: __init__.py for escalation test dir inconsistent with majority convention
**Severity:** P4
Only frequency/ has one among 8 adversarial subdirs. Harmless.

### F-3: Brief RATE_LIMITED_RESULT.tier changed from "rate_limited" to "none" (category c)
**Severity:** P3
Decision 4 has explicit rationale. Flagging for human drift-check.

### F-4: Brief benchmark criterion deferred to Out-of-scope (category c)
**Severity:** P3
Functional behavior tested; benchmark assertion deferred.

### F-5: Hardcoded threshold vs brief "configurable" (category c)
**Severity:** P3
Decision 1 has rationale.

### F-6: derive_tier() NaN fail-closed is new behavior (category c)
**Severity:** P3
Defensively correct. Flagging for human acknowledgment.

### F-7: Standalone sets escalation_tier without premium — intentional convention break
**Severity:** P2
Decision 1 is explicit about this. Should add inline comment in code.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 4 | P4: 1

STATUS: GREEN
