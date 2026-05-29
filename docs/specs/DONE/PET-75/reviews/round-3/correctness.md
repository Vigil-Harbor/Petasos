# Correctness Review — PET-75 Round 3

## Closure of round 2 findings
All round 2 findings CLOSED. `_compact_ttl_deque` now sorts entries (entries.sort()), test 3 uses premium-active path, test 5 added for severity-override interaction, Stage 5a comment updated.

## Findings

### F-1: Test 5 severity downgrades are blocked by PET-54 independently
**Severity:** P2
Test 5 claims to prove standalone check ran before severity overrides, but PET-54 blocks severity downgrades (CRITICAL→HIGH) regardless of ordering. Test still validates both protections work together.

### F-2: ESC-03 test numbering overlaps with ESC-01 (duplicate test 5)
**Severity:** P4
ESC-03 tests numbered 5-8, but ESC-01 already has test 5. Total count (17) is correct.

### F-3: Test 3 parenthetical "(from fail-mode)" is misleading
**Severity:** P4
safe=False comes from CRITICAL findings severity check, not from fail-mode enforcement.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 0 | P4: 2

STATUS: GREEN
