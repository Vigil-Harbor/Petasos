# PET-35 Edge-Cases Review — Round 1

## Findings

### F-1: casefold/lower mismatch between guard normalization and profile exempt-list storage (P1)
`tool_exempt_list` built with `.lower()` in `profiles/__init__.py:79`, but spec's GUARD-03 check uses `.casefold()`. For ASCII identical, but spec's own Decision 2 motivates casefold for Unicode correctness — implying profiles should also migrate.

### F-2: Profile alias-map keys are not casefolded — lookup misses cased profile aliases (P1)
Profile alias keys stored as-is from JSON. After casefold normalization, casefolded tool names won't match non-casefolded alias keys. Pre-existing behavior (`.lower()` also mismatches uppercase keys), but spec doesn't address.

### F-3: No test for empty-string tool name (P2)
`_normalize_tool_name("")` returns `""` — correct, caught by evaluate(), but untested through new pipeline.

### F-4: No test for whitespace-only tool name (P2)
`_normalize_tool_name("   ")` → strip → `""` — correct, but untested after strip reorder.

### F-5: GUARD-03 check doesn't casefold profile alias-map keys (P2)
Same root cause as F-2. `name in self._profile.tool_alias_map` compares casefolded name against non-casefolded keys.

### F-6: Namespace regex `[a-zA-Z0-9_]` has dead A-Z range after casefold (P3)
After casefold, only lowercase chars exist. The `A-Z` in the regex is unreachable. Cosmetic.

### F-7: No test for invisible/zero-width characters (P2)
`"ba​sh"` stays as-is (NFKC doesn't strip U+200B). Known out-of-scope gap but no negative test documenting it.

### F-8: NFKC normalization of namespace prefix — undocumented behavioral change (P3)
Fullwidth namespace prefix chars (e.g., fullwidth underscores) now get NFKC-normalized before regex strip, changing which prefixes get stripped. A security improvement but not called out.

## Summary
P0: 0 | P1: 2 | P2: 3 | P3: 2 | P4: 0

STATUS: RED P0=0 P1=2 P2=3 P3=2 P4=0
