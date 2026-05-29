# Edge-Cases Review — PET-75 Round 2

## Closure of round 1 findings
All 23 round 1 findings across 3 lenses CLOSED with evidence.

## Findings

### F-1: `_compact_ttl_deque` unsorted deque breaks eviction loop
**Severity:** P1
Same root as correctness P0. Dict insertion order != expiry order after refreshes. Eviction loop stops at first non-expired front entry, stranding truly expired sessions behind it.

### F-2: Standalone tier-3 sets escalation_tier in non-premium path
**Severity:** P2
When premium is inactive, escalation_tier was None. Standalone check overrides to "tier3". Downstream callers may interpret non-None as "premium ran." No crash but semantic leak.

### F-3: Test 3 passes trivially without standalone check
**Severity:** P2
With frequency_enabled=False and no premium, escalation_tier is always None regardless of finding count.

### F-4: No test for profile severity-override interaction
**Severity:** P2
No test proves profiles cannot suppress the standalone check via severity overrides.

### F-5: Code comment at Stage 5a incomplete
**Severity:** P2
Says "profiles cannot suppress CRITICAL count" but doesn't mention confidence floor.

### F-6: Test 15 (compaction) doesn't verify sort order
**Severity:** P3
Compaction test checks size but not ordering invariant.

### F-7: Module-level function is unusual for pipeline.py
**Severity:** P3
Intentional design choice per Decision 1.

## Summary
P0: 0 | P1: 1 | P2: 4 | P3: 2 | P4: 0

STATUS: RED P0=0 P1=1 P2=4 P3=2 P4=0
