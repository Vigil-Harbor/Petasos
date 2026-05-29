# Edge-Cases Review -- round 2

## Closure of round 1 findings

All round 1 findings CLOSED:
- F-1 (P2): Concrete test body with baseline assertion (spec L166-178)
- F-2 (P2): Concrete test body with baseline assertions for both categories (spec L184-196)
- F-3 (P2): Full import block specified (spec L152-161)
- F-4 (P3): Idempotency documented in D2 (spec L42)
- F-5 (P2): Dead try/except removal specified (spec L103, L223, L241)
- F-6 (P3): Test mapping complete across Tests NOT added, Deferred, and new tests sections
- F-7 (P3): Done-When L243 explicitly acknowledges PET-59 coverage
- F-8 (P2): Same as correctness F-1, CLOSED
- F-9 (P2): Xfail reason updated to acknowledge already-realized failure

## Findings

### F-1: Zero-width space literal in spec code blocks may not survive rendering/copy-paste
**Severity:** P2
Spec L169 and L187 embed literal U+200B. Should use `"​"` escape sequence for copy-paste safety.

### F-2: `test_suppress_encoding_rules_allowed` text triggers only 2 of 4 encoding rules
**Severity:** P3 (advisory)

### F-3: Escalation interaction in mixed test not documented
**Severity:** P3 (advisory)

### F-4: Triple-strip path (parse -> __post_init__ -> scanner) not explicitly documented
**Severity:** P3 (advisory)

### F-5: Unknown rule IDs in suppress_rules silently ignored
**Severity:** P3 (pre-existing behavior, not introduced by this spec)

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 4 | P4: 0

STATUS: GREEN
