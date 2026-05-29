# Edge-Cases Review — Round 1

### F-1 (P1): Spec and brief disagree on `_EXTRA_INVISIBLE` contents — U+202F in spec, absent from brief
The spec's `_EXTRA_INVISIBLE` = {U+2800, U+202F, U+180E}. The brief's = {U+2800, U+180E, U+00AD}. Spec drops U+00AD (redundant, Cf) and adds U+202F (Zs, required for backward-compatible counting). Spec is correct but should explicitly flag the deviation.

### F-2 (P3): Double iteration for stripping (O(2n)) where O(n) suffices
Current code has same pattern. Not a regression. Could be optimized in a single pass.

### F-3 (P2): Stripping Arabic format characters (U+0600–U+0605, U+06DD, U+061C) may corrupt legitimate Arabic text
Cf category includes 161+ codepoints. Arabic number signs and end-of-ayah markers are Cf and would be stripped. Document the trade-off explicitly.

### F-4 (P2): Test #10 doesn't specify how existing `INVISIBLE_CHARS` assertion and docstring evolve
The spec says "tag char IS stripped" but doesn't detail what to do with `assert _TAG not in INVISIBLE_CHARS` or the docstring.

### F-5 (P2): `strip_zero_width=False` config toggle bypasses normalization entirely
Pre-existing behavior. MinimalScanner always normalizes internally. Spec should note this config interaction for completeness.

### F-6 (P4): No test for empty string through `_is_strippable()`
Covered by existing `normalize("")` test. Safe in practice.

### F-7 (P4): Spec line references to normalize.py may become stale
Expected drift. Standard practice.

### F-8 (P2): Test #11 calling convention ambiguous — raw vs pre-normalized text to scanner
Spec says "after normalize + scan" but should clarify test passes raw payload to `scanner.scan()`.

P0: 0 | P1: 1 | P2: 4 | P3: 1 | P4: 2

STATUS: RED P0=0 P1=1 P2=4 P3=1 P4=2
