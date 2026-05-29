# Edge-Cases Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: Micro sign (U+00B5) homoglyph entry is dead code due to NFKC ordering (P1)
Cross-lens overlap with correctness F-1. Same issue and fix.

### F-2: Idempotency violation with Hangul + combining marks (P2)
Input with Hangul syllable + combining mark: first pass NFD-decomposes Hangul to Jamo, strips Mn. Second pass: mn_count==0, uses text_after_restrip (NFKC form), recomposes Jamo. Result differs. Fix: NFC-recompose after Mn strip.

### F-3: invisible_chars_stripped counter not updated for re-strip pass (P2)
Re-strip pass removes chars but doesn't increment the counter. MinimalScanner uses this counter for encoding findings. Fix: accumulate restrip_count into stripped_count.

### F-4: Test #2 cannot exercise the re-strip code path (P2)
Cross-lens overlap with correctness F-2. Same issue.

### F-5: No MinimalScanner encoding finding for combining mark stripping (P3)
Combining mark attacks leave no audit signal beyond the injection finding itself. Out of scope for this spec but should be noted.

### F-6: Performance regression on max-size payloads (P3)
6-step pipeline adds ~10 passes. Pre-existing 5ms budget was already not met on max payloads. Document as known.

### F-7: Greek eta mapped to "n" is a weak visual confusable (P4)
Font-dependent. Brief lists it. Accepted.

## Summary
P0: 0 | P1: 1 | P2: 3 | P3: 2 | P4: 1

STATUS: RED P0=0 P1=1 P2=3 P3=2 P4=1
