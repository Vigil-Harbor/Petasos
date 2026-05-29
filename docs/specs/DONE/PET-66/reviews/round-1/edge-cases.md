# Edge-Cases Review -- round 1

## Findings

### F-1: Test #6 name says "role_trigger" but tests injection pattern (P4)
`"you  are  now"` matches `_INJECTION_PATTERNS` (slug `you-are-now`), not `_ROLE_TRIGGERS` (`you\s+are\s+a`).

### F-2: No test for role-trigger-only path with double-space evasion (P2)
No test verifies `"pretend  you  are an assistant"` (no grant) produces `role-switch-only` finding.

### F-3: No test for individual `_ROLE_GRANTS` patterns with whitespace evasion (P3)
Only `no  restrictions` tested via combo test #7. Other grants untested individually.

### F-4: Test #9 ReDoS input does not exercise 3-segment pattern fully (P3)
Missing third word `instructions` means second `\s+` backtrack not fully exercised. Patterns are empirically safe regardless.

### F-5: D1 doesn't acknowledge invisible-char-only separator gap (P3)
ZWSP-only separators are stripped by normalize(), concatenating words. Pre-existing gap, not introduced by this spec.

### F-6: Test #7 input changed from brief (P4)
Spec's version is more correct (includes trigger for full path exercise).

### F-7: `\s+` matches CRLF as two chars — Windows line-ending interaction (P3)
`matched_text` will contain raw newlines when match spans line boundaries. Pre-existing concern expanded to 6 more patterns.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 3 | P4: 3

STATUS: GREEN
