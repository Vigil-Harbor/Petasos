# PET-44 — Normalize Hardening: NORM-02 through NORM-05

**Plane items:** PET-44 (NORM-02), PET-45 (NORM-03), PET-46 (NORM-04), PET-47 (NORM-05)
**Files touched:** `petasos/normalize.py`, `tests/test_normalize.py`, `tests/adversarial/normalization/`
**Parent:** PET-14 (red-team security review)
**Blocks:** PET-12 (release)

> **NORM-01 (PET-43) is already shipped.** The category-based `_is_strippable()` predicate, `_STRIP_CATEGORIES`, and `_EXTRA_INVISIBLE` are in place. This brief covers the remaining 4 findings.

## Findings

| ID | Severity | Attack | Current behavior | Remediation |
|----|----------|--------|------------------|-------------|
| NORM-02 | low | NFKC compatibility mapping after strip | Strip runs before NFKC; NFKC could theoretically reintroduce a strippable char (rare) | Add a second strip pass after NFKC |
| NORM-03 | medium | Cyrillic k, x, fullwidth variants | `_HOMOGLYPH_TABLE` has only 17 lowercase Cyrillic/Greek mappings; unmapped confusables evade fold | Expand table: add Cyrillic lowercase + uppercase, Greek extras, other confusables |
| NORM-04 | medium | Combining marks (NFD) between letters | No combining-mark removal; injecting U+0300 COMBINING GRAVE between "i" and "g" can split regex triggers | After NFKC, NFD-decompose then strip Mn (nonspacing marks) |
| NORM-05 | low | RTL chars in INVISIBLE_CHARS overlap, manual sync brittle | `RTL_OVERRIDES` and `INVISIBLE_CHARS` are manually maintained frozensets; adding to one but not the other breaks stripping | Refactor `RTL_OVERRIDES` to `chr()` form; validate all members are strippable via test |

## Approach

Extend the existing `normalize()` pipeline (4 steps) to 6 steps:

1. RTL override detection (before stripping) -- **existing, unchanged**
2. Strip invisible chars (category-based via `_is_strippable`) -- **existing (PET-43)**
3. NFKC normalization -- **existing, unchanged**
4. **Re-strip after NFKC** (NORM-02 -- catches any Cf chars NFKC preserved/reintroduced)
5. **NFD decompose + strip Mn** (NORM-04 -- remove combining marks to recover base characters)
6. Homoglyph mapping (expanded table, NORM-03) -- **existing step, expanded table**

NORM-05 is addressed by refactoring `RTL_OVERRIDES` to use `chr()` notation and adding a test that validates every member is `_is_strippable()`.

## Decisions carried forward

- **Confusables library vs. curated table:** A library (e.g. `confusables` PyPI) would be comprehensive but adds a runtime dep to the zero-dep base install. Decision: expand the curated table to ~50 mappings covering Latin/Cyrillic/Greek uppercase and lowercase. Document the omitted tail in a comment.
- **Combining mark removal is lossy:** Stripping Mn chars removes legitimate diacritics (e.g. e + accent -> e). Acceptable for security scanning context where normalized text is only used for pattern matching. `NormalizedText.original` preserves untouched input.
- **Fullwidth chars already handled by NFKC:** All 94 fullwidth ASCII variants (U+FF01-FF5E) are mapped to ASCII by NFKC. No need to duplicate in the homoglyph table.

## Done when

- [ ] Second strip pass after NFKC exists (NORM-02)
- [ ] `_HOMOGLYPH_TABLE` has >= 40 mappings covering Cyrillic lowercase + uppercase, Greek extras
- [ ] Combining mark (Mn) stripping pass exists after NFKC via NFD decomposition (NORM-04)
- [ ] `RTL_OVERRIDES` refactored to `chr()` form with validation test (NORM-05)
- [ ] Combining mark injection attack ("ign" + U+0301 + "ore") is defeated: normalized text = "ignore"
- [ ] Cyrillic ka (U+043A) mapped to 'k' in homoglyph table
- [ ] Adversarial tests for each finding
- [ ] Existing normalization tests still pass
- [ ] `mypy --strict` clean, `ruff` clean

## Out of scope

- Full Unicode confusables library integration (future, if needed)
- Normalization of non-Latin scripts beyond confusable mapping (CJK, Arabic, Devanagari)
- NORM-01 / PET-43 (already shipped)
- Regex whitespace flexibility (PET-66 / SYN-02 -- complementary, independent)
