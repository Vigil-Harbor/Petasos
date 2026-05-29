# Conventions Review — Round 1

### F-1 (P2): D3 deprecation via comment-only — first deprecation in repo, no precedent
No `deprecated` annotations exist in the codebase. The repo is pre-release (0.0.1). `INVISIBLE_CHARS` is not exported in `__init__.py`. Only consumer is the adversarial test file. Consider removing entirely or documenting the convention.

### F-2 (P3): `_EXTRA_INVISIBLE` diverges from brief without flagging as spec-level change
Silent addition of U+202F, silent removal of U+00AD. Should be documented as a brief deviation.

### F-3 (P3): Spec test #10 semantics diverge from brief's `test_tag_char_injection_now_detected`
Spec corrects a brief error (no-space payload can't match literal-space regex). D6 explains this correctly.

### F-4 (P3): D2 drops `test_variation_selectors_stripped` — brief's table was factually wrong about Cf
Correctly dropped. Variation selectors are Mn, not Cf. D2 rationale is sound.

### F-5 (P2): `_EXTRA_INVISIBLE` code block embeds literal invisible Unicode characters
Adversarial test file uses `chr()` pattern for reviewability. Spec should use `chr()` or `\uXXXX` escapes.

### F-6 (P2): Spec doesn't specify how to handle `INVISIBLE_CHARS` import in adversarial test
Test file imports `INVISIBLE_CHARS`. Spec should specify whether the import stays, assertion evolves, or import is removed.

### F-7 (P4): Test 11 in normalization file but tests scanning — matches existing pattern
Existing test in same file already mixes normalize + scan. Not a violation.

### F-8 (P4): U+180E in `_EXTRA_INVISIBLE` is redundant (already Cf) — acknowledged as belt-and-suspenders
Harmless redundancy. No change needed.

P0: 0 | P1: 0 | P2: 3 | P3: 3 | P4: 2

STATUS: GREEN
