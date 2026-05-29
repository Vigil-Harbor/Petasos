# Edge-Cases Review — Round 2

## Closure table
All round 1 P1/P2 findings CLOSED:
- F-1 (P1): Brief deviation note added → CLOSED
- F-3 (P2): Arabic Cf trade-off documented → CLOSED
- F-4 (P2): Test #10 assertion-level detail added → CLOSED
- F-5 (P2): Config toggle note added → CLOSED
- F-8 (P2): Test #11 raw payload clarified → CLOSED

## Findings

### F-1 (P2): Test #10 conditional import removal is unnecessarily ambiguous
The spec says "Remove INVISIBLE_CHARS if no other test uses it" — but `test_nbsp_u00a0_not_in_invisible_set_but_nfkc_collapses` does use it. The conditional resolves to "keep the import." State the answer directly.

### F-4 (P4): Test #2 range U+E0001–U+E007F includes 30 unassigned (Cn) codepoints
Only 97 of 127 chars in that range are Cf. Test should assert per-char `category == 'Cf' implies stripped`, not blanket "all stripped."

### F-6 (P3): Performance at max payload — category lookup ~6x slower than frozenset
Typical payloads <10K add <1ms. Max 512KB adds ~44ms. Acceptable because max-payload already triggers oversized-payload finding.

P0: 0 | P1: 0 | P2: 1 | P3: 1 | P4: 1 (+ 4 more P4 nits)

STATUS: GREEN
