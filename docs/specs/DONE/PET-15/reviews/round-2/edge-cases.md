# Edge-Cases Review — Round 2

## Closure of round 1 findings

All 12 round-1 findings (across all lenses) closed or deferred. See correctness round-2 closure table for full cross-lens status.

## Findings

### F-1: Tag char produces zero findings pre-fix — vacuously true assertion (P3)
The baseline "no HIGH/CRITICAL findings" is correct but trivially satisfied — total finding count from MinimalScanner is zero. Informational only.

### F-2: _CleanMLScanner code sample not shown (P4)
Only prose description. Implementer can infer from sibling test pattern.

### F-3: Test 5 does not exercise SYN-08 (Link 2) (P3)
Brief says "suppression should be rejected" in test 5 but spec's test 5 uses no profile. SYN-08 tested in isolation in test 3. Pragmatically correct per D1/D4.

### F-4: Test 2 NORM-01 fix approach affects invisible-char findings (P2)
Test 2 assertions are robust to either PET-43 approach ("at least one injection finding" works regardless). The presence of invisible-char escalation depends on implementation.

### F-5: xfail strict=False baseline lifecycle — fix-order analysis (P2)
Analyzed all fix-ordering permutations. The xfail strategy is sound for all orderings. Informational.

## Summary
P0: 0 | P1: 0 | P2: 2

STATUS: GREEN
