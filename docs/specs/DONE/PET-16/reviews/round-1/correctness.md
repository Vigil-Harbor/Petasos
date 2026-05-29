# Correctness Review — PET-16 Round 1

## Findings

### F-1: Spec line number range "L95-121" is off-by-one (P4)
**Where:** spec.md:92
**Claim:** "Replace the unconditional critical pass-through at L95-121"
**Actual:** L95-120 is the decision block; L121 is a blank line. The code block provided in the spec is correct regardless.
**Suggested fix:** Cosmetic; no change needed.

### F-2: Test 5 described as "meta-test" but is actually a new standalone test (P3)
**Where:** spec.md:168, 175-176
**Issue:** The test table says "existing tests still pass" but the test plan body (L191) defines a new test with specific params. The test plan body is authoritative.
**Suggested fix:** Remove "meta-test" framing; describe it as what it is.

### F-3: Test 3 detail discussion is self-contradictory before reaching a conclusion (P3)
**Where:** spec.md:171
**Issue:** 12-line stream-of-consciousness exploring approaches. The clean version is in the Test plan section at L187.
**Suggested fix:** Trim to match the Test plan description.

### F-4: Config validation tests listed but not counted in "6 new tests" (P2)
**Where:** spec.md:199-204, 218
**Issue:** Done-when says "All 6 new TestCriticalCap tests" but 3 config validation tests are also proposed. Not in formal acceptance criteria.
**Suggested fix:** Add a Done-when line for config tests or fold into the count.

### F-5: Brief vs spec line references for _prune_stale (P4)
**Where:** brief L69, spec.md:144
**Issue:** Both are accurate; they reference different sub-blocks (minute vs hour pruning).

### F-6: Test 4 mocking interaction with _prune_stale (P3)
**Where:** spec.md:173, 189
**Issue:** The mock pattern works correctly; existing tests demonstrate the precedent.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 3 | P4: 2

STATUS: GREEN
