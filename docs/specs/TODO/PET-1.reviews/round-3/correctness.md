# PET-1 Spec Review — Correctness (Round 3)

**Spec:** `docs/specs/TODO/PET-1.spec.md`
**Brief:** `docs/briefs/PET-1-brief.md`
**Round:** 3

---

## Closure of round 2 findings

| Finding | Status | Evidence |
|---------|--------|----------|
| R2/F-1 (confusables_normalized scoped narrower than Drawbridge) | CLOSED | Line 316 now matches Drawbridge: compares after steps 3+4 vs after step 2 |
| R2/F-2 (D3 says all types get to_dict() but only two do) | CLOSED | D3 (line 71) scoped to ScanFinding/ScanResult; others deferred |
| R2/F-3 (Processing order step 5 conflates metadata vs raw input) | CLOSED | Line 423 disambiguated |
| R2/F-6 (Unused field import) | CLOSED | Import removed |

---

## Findings

### F-1 [P2] D1 homoglyph table breakdown miscounts

D1 says "8 Cyrillic, 6 Greek, 2 Latin, 1 IPA" but actual table is 8 Cyrillic, 7 Greek, 1 Latin, 1 IPA. Total 17 is correct; breakdown is off by one in Greek and Latin.

### F-2 [P3] INVISIBLE_CHARS missing U+2065

Drawbridge range includes reserved U+2065. Negligible risk.

### F-3 [P3] Plane ticket not cached in MCP memory

MCP search returns zero results. Brief used as canonical source.

---

STATUS: GREEN
