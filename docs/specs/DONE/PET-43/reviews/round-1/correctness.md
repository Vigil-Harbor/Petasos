# Correctness Review — Round 1

### F-1 (P3): `_EXTRA_INVISIBLE` diverges from brief without explicit callout
The spec replaces U+00AD (redundant, Cf) with U+202F (Zs, required for backward compat). Change is correct but should be noted as a brief deviation.

### F-2 (P3): Brief test `test_tag_char_injection_now_detected` semantics differ from spec test #10
The brief's test expects injection detection after stripping a no-space payload — incorrect because the regex requires a literal space. Spec's D6 correctly identifies this. Not a defect.

### F-3 (P4): Double iteration over input string in strip stage
Counts then filters — matches existing code pattern. Not a regression.

### F-4 (P4): Scope file counts verified consistent
"Add 9 tests" matches 9-row table. Correct.

P0: 0 | P1: 0 | P2: 0 | P3: 2 | P4: 2

STATUS: GREEN
