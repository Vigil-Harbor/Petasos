# Correctness Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: Micro sign (U+00B5) homoglyph entry is dead code -- NFKC converts it to Greek mu before homoglyph step (P1)
NFKC (step 3) maps U+00B5 (MICRO SIGN) to U+03BC (GREEK SMALL LETTER MU). The homoglyph table key U+00B5 will never match any character at step 6. The micro sign passes through unmapped. Fix: replace with U+03BC entry, or add both.

### F-2: Test #2 description is infeasible -- ZWSP is stripped in step 2, cannot reach step 4 (P1)
U+200B (ZWSP) has category Cf and is stripped in step 2 before NFKC ever runs. D1 confirms no non-Cf char produces Cf under NFKC in BMP. The test as described cannot exercise the re-strip path. Fix: reframe as defense-in-depth wiring test or unit-test the filter directly.

### F-3: D3 summary table count ("~45-50") disagrees with code block count (44) (P2)
D3 table total says "~45-50" but code block counts 44 entries. Roman numeral entry is NFKC-handled and excluded from code block. Fix: update D3 table total to 44.

### F-4: D3 table counts micro sign separately from Greek (P4)
Cosmetic inconsistency only. No action needed.

## Summary
P0: 0 | P1: 2 | P2: 1 | P3: 0 | P4: 1

STATUS: RED P0=0 P1=2 P2=1 P3=0 P4=1
