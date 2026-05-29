# PET-35 Edge-Cases Review — Round 2

## Closure of round 1 findings
All round 1 edge-cases findings CLOSED. F-1 (P1) closed by Decision 6 + Design §3. F-2 (P1) closed by Decision 7. F-3/F-4/F-7 (P2) closed by new tests 8, 9, 4. F-5 closed by Decision 7. F-6/F-8 (P3) addressed.

## Findings

### F-7: Alias value not casefolded before return — `_normalize_tool_name` returns mixed-case output (P1)
After alias lookup replaces the casefolded tool name with a raw alias value, the returned string is not casefolded. Profile alias values with non-lowercase chars produce a `normalized_name` that doesn't match the casefolded exempt set. Pre-existing gap (current code has same issue with `.lower()`), but PET-35 is rewriting the method for normalization correctness — should fix while here. One-line fix: `return resolved.strip().casefold()`.

### F-1: `None` input to `_normalize_tool_name` (P3)
No runtime guard for `None`. Static typing catches at caller boundary. Internal API.

### F-3: Adversarial test ZWS relies on source-file encoding (P3)
ZWS character should use `​` escape sequence, not literal invisible char.

### F-6: No test for multiple simultaneous Cyrillic substitutions (P3)
Tests cover single-char substitution only. Nice-to-have multi-char test.

### F-8: Test 6 naming slightly misleading (P4)
"namespace prefix with cyrillic" — Cyrillic is in the tool name portion, not the prefix.

## Summary
P0: 0 | P1: 1 | P2: 0 | P3: 3 | P4: 1

STATUS: RED P0=0 P1=1 P2=0 P3=3 P4=1
