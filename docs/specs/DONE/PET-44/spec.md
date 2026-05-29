# PET-44 — Normalize Hardening: NORM-02, NORM-03, NORM-04, NORM-05

**Tickets:** PET-44 (NORM-02), PET-45 (NORM-03), PET-46 (NORM-04), PET-47 (NORM-05)
**Parent:** PET-14 (red-team) | **Blocks:** PET-12 (release)
**Prerequisite:** PET-43 (NORM-01, shipped) — `_is_strippable()`, `_STRIP_CATEGORIES`, `_EXTRA_INVISIBLE` already in place.

## Goal

Harden `normalize()` with four additional security layers to close the remaining Unicode evasion gaps identified by PET-14 red-team. Adds a re-strip pass after NFKC (NORM-02), combining mark removal via NFD decomposition (NORM-04), an expanded homoglyph table with ~50 mappings covering Cyrillic/Greek uppercase and lowercase confusables (NORM-03), and programmatic validation of the RTL override set (NORM-05). After this change, the `normalize()` pipeline runs 6 steps: RTL detect → strip invisible → NFKC → re-strip → NFD + strip Mn → homoglyph map.

## Scope

### Files changed

| File | Change |
|------|--------|
| `petasos/normalize.py` | Add re-strip pass (step 4), NFD + Mn strip pass (step 5), expand `_HOMOGLYPH_TABLE` to ~50 entries, refactor `RTL_OVERRIDES` to `chr()` form |
| `tests/test_normalize.py` | Add tests for re-strip, combining mark removal, expanded homoglyphs, RTL validation |
| `tests/adversarial/normalization/test_unicode_bypass.py` | Update NORM-03/NORM-04 adversarial tests to assert fixes |

### Files left alone

- `petasos/scanners/minimal.py` — fixes are in the normalizer; scanner regexes fire on normalized text
- `petasos/_types.py` — `NormalizedText` dataclass unchanged (no new fields needed)
- `petasos/pipeline.py` — `Pipeline.inspect()` already calls `normalize()` before scanning
- `petasos/config.py` — no config changes (combining mark removal is unconditional; see D5)
- `petasos/premium/guard.py` — imports `_HOMOGLYPH_TABLE` from `normalize.py` for tool name normalization (PET-35/GUARD-02). Table expansion automatically applies. No code change needed

## Decisions

### D1: Re-strip after NFKC is belt-and-suspenders (NORM-02)

Empirical scan of BMP confirms NFKC maps Cf chars to Cf chars (identity) — no non-Cf char produces a Cf char under NFKC in the BMP. The re-strip pass is therefore defense-in-depth against exotic SMP sequences or future Unicode version changes. Cost: one additional `_is_strippable()` filter pass (O(n), negligible). The transformation name `nfkc_restrip_applied` is appended only when chars are actually stripped, preserving clean `transformations_applied` tuples for normal input.

### D2: NFD decompose then strip Mn (NORM-04)

The attack: inserting U+0301 (COMBINING ACUTE ACCENT) between trigger letters ("ign" + U+0301 + "ore") causes NFKC to compose "n" + U+0301 → "ń" (U+0144), a single precomposed character. The regex for "ignore" never matches "igńore".

The fix: after NFKC (and re-strip), NFD-decompose the text to separate base characters from combining marks, then strip all Mn (nonspacing mark) characters. This restores the base characters: "ń" → NFD → "n" + U+0301 → strip Mn → "n". Result: "ignore" matches.

**This is lossy by design.** Legitimate diacritics (French "é", Spanish "ñ") are stripped. This is acceptable because: (a) normalized text is used only for pattern matching, never displayed to users; (b) `NormalizedText.original` preserves the untouched input; (c) the brief explicitly accepts this trade-off.

### D3: Expanded homoglyph table — curated, not library (NORM-03)

Expand `_HOMOGLYPH_TABLE` from 17 to ~50 entries. Coverage:

| Script | Lowercase | Uppercase | Count |
|--------|-----------|-----------|-------|
| Cyrillic (existing) | а, е, о, р, с, у, і, ѕ | — | 8 |
| Cyrillic (new) | к→k, х→x, н→h, т→t, м→m | А→A, Е→E, О→O, Р→P, С→C, К→K, Х→X, Н→H, Т→T, М→M | 15 |
| Greek (existing) | α, ε, ο, ρ, κ, ι, ν | — | 7 |
| Greek (new) | τ→t, η→n | Α→A, Ε→E, Ο→O, Ρ→P, Κ→K, Ι→I, Ν→N, Τ→T, Η→H | 11 |
| Greek mu | μ (U+03BC) → u | — | 1 |
| Latin/IPA (existing) | ı→i, ɡ→g | — | 2 |
| **Total** | | | **44** |

Fullwidth A-Z/a-z are omitted — NFKC already maps all 94 fullwidth ASCII variants to their ASCII equivalents. Adding them to the table would be redundant.

A confusables library (`confusables` PyPI) would be comprehensive but adds a runtime dependency to the zero-dep base install. Decision: curate 44 high-confidence visual confusables. Document the omitted tail. Revisit if evasion reports accumulate.

**Note on U+00B5 (MICRO SIGN):** NFKC maps U+00B5 to U+03BC (GREEK SMALL LETTER MU) in step 3. The homoglyph table runs at step 6, so the key must be U+03BC (the NFKC output), not U+00B5. An entry for U+00B5 would be dead code.

### D4: RTL_OVERRIDES refactored to chr() form + validation (NORM-05)

Replace the literal invisible characters in `RTL_OVERRIDES` with explicit `chr()` calls for readability and diffability, matching the pattern used in `_EXTRA_INVISIBLE`. Add a test that validates every member of `RTL_OVERRIDES` is `_is_strippable()` — this ensures the "shared source" invariant holds without expensive runtime derivation.

The RTL detection step (step 1) continues to run on the original text before stripping, which is correct — RTL override chars are Cf and get stripped in step 2.

### D5: Combining mark stripping is unconditional (no config toggle)

The existing pipeline has individual config toggles for normalization steps (`normalize_nfkc`, `strip_zero_width`, `map_homoglyphs`, `detect_rtl_override`). The new NFD + Mn strip step has no toggle. This is a deliberate spec addition not explicitly stated in the brief.

Rationale: disabling combining mark stripping would reintroduce the NORM-04 attack vector (inserting combining marks between trigger letters to evade injection regex). Unlike homoglyph mapping (which has false-positive risk on legitimate multilingual text), combining mark stripping operates on a proven attack technique with no legitimate use case in LLM prompt security scanning. Making it unconditional prevents misconfiguration.

### D6: Pipeline step ordering

After all changes, `normalize()` runs 6 steps:

```
1. RTL detection (on original text)     — unchanged
2. Strip invisible (Cf-based)           — PET-43, unchanged
3. NFKC normalization                   — unchanged
4. Re-strip after NFKC                  — NEW (NORM-02)
5. NFD decompose + strip Mn             — NEW (NORM-04)
6. Homoglyph mapping (expanded table)   — MODIFIED (NORM-03)
```

Ordering rationale:
- Step 4 (re-strip) must follow NFKC to catch any reintroduced Cf chars.
- Step 5 (Mn strip) must follow NFKC because NFKC composes marks with base chars; NFD re-decomposes them so we can strip the marks.
- Step 6 (homoglyph) must be last because Cyrillic/Greek confusables should be mapped after all normalization and stripping is complete.

## Design

### NORM-02: Re-strip after NFKC

Insert between current steps 3 and 4 (after NFKC, before homoglyph mapping):

```python
# Step 4: Re-strip after NFKC (NORM-02)
restrip_count = sum(1 for ch in text_after_nfkc if _is_strippable(ch))
if restrip_count > 0:
    text_after_restrip = "".join(ch for ch in text_after_nfkc if not _is_strippable(ch))
    stripped_count += restrip_count
    transforms.append("nfkc_restrip_applied")
else:
    text_after_restrip = text_after_nfkc
```

Note: `restrip_count` is accumulated into `stripped_count` so that `NormalizedText.invisible_chars_stripped` reflects the total across both strip passes. `MinimalScanner._check_encoding()` uses this counter to emit the `invisible-chars` encoding finding.

### NORM-04: NFD + strip Mn

Insert after re-strip, before homoglyph mapping:

```python
# Step 5: Combining mark removal (NORM-04)
text_nfd = unicodedata.normalize("NFD", text_after_restrip)
mn_count = sum(1 for ch in text_nfd if unicodedata.category(ch) == "Mn")
if mn_count > 0:
    text_stripped_mn = "".join(
        ch for ch in text_nfd if unicodedata.category(ch) != "Mn"
    )
    text_after_mn = unicodedata.normalize("NFC", text_stripped_mn)
    transforms.append("combining_marks_stripped")
else:
    text_after_mn = text_after_restrip
```

Key details:
- When `mn_count == 0`, we use `text_after_restrip` (not `text_nfd`) to avoid unnecessary NFD decomposition artifacts in the output.
- When `mn_count > 0`, we NFC-recompose after stripping Mn chars. This is critical for idempotency: without NFC, Hangul syllables (or other canonically decomposable sequences) remain as Jamo after NFD, but a second `normalize()` pass would skip NFD (no Mn marks) and use the NFKC form (which recomposes Jamo). NFC ensures the output is stable under re-normalization.

### NORM-03: Expanded homoglyph table

Replace `_HOMOGLYPH_TABLE` with an expanded version. The table uses `str.maketrans()` as before. New entries are grouped by script with comments:

```python
_HOMOGLYPH_TABLE = str.maketrans(
    {
        # --- Cyrillic lowercase (existing + new) ---
        "а": "a",  # а
        "е": "e",  # е
        "о": "o",  # о
        "р": "p",  # р
        "с": "c",  # с
        "у": "y",  # у
        "і": "i",  # і
        "ѕ": "s",  # ѕ
        "к": "k",  # к  (NEW)
        "х": "x",  # х  (NEW)
        "н": "h",  # н  (NEW)
        "т": "t",  # т  (NEW)
        "м": "m",  # м  (NEW)
        # --- Cyrillic uppercase (NEW) ---
        "А": "A",  # А
        "Е": "E",  # Е
        "О": "O",  # О
        "Р": "P",  # Р
        "С": "C",  # С
        "К": "K",  # К
        "Х": "X",  # Х
        "Н": "H",  # Н
        "Т": "T",  # Т
        "М": "M",  # М
        # --- Greek lowercase (existing + new) ---
        "α": "a",  # α
        "ε": "e",  # ε
        "ο": "o",  # ο
        "ρ": "p",  # ρ
        "κ": "k",  # κ
        "ι": "i",  # ι
        "ν": "v",  # ν
        "τ": "t",  # τ  (NEW)
        "η": "n",  # η  (NEW)
        "μ": "u",  # μ Greek mu (U+03BC, NFKC target of micro sign)  (NEW)
        # --- Greek uppercase (NEW) ---
        "Α": "A",  # Α
        "Ε": "E",  # Ε
        "Ο": "O",  # Ο
        "Ρ": "P",  # Ρ
        "Κ": "K",  # Κ
        "Ι": "I",  # Ι
        "Ν": "N",  # Ν
        "Τ": "T",  # Τ
        "Η": "H",  # Η
        # --- Latin / IPA (existing) ---
        "ı": "i",  # ı dotless i
        "ɡ": "g",  # ɡ IPA g
    }
)
```

Total: 13 Cyrillic lowercase + 10 Cyrillic uppercase + 10 Greek lowercase + 9 Greek uppercase + 2 Latin/IPA = **44 entries**. The `translate()` call is unchanged — `str.maketrans()` handles the mapping automatically.

The homoglyph table retains literal non-ASCII chars (unlike `_EXTRA_INVISIBLE` which uses `chr()`) because the visual correspondence between source glyph and target letter is the primary audit signal for reviewers.

**Step 6 code** (updated to use `text_after_mn` from step 5):

```python
# Step 6: Homoglyph mapping (expanded table, NORM-03)
text_after_homoglyph = text_after_mn.translate(_HOMOGLYPH_TABLE)
if text_after_homoglyph != text_after_mn:
    transforms.append("homoglyph_mapped")
confusables = text_after_homoglyph != text_after_mn
```

**Cross-surface impact:** `petasos/premium/guard.py` imports `_HOMOGLYPH_TABLE` from `normalize.py` and uses it in `_normalize_tool_name()` (PET-35/GUARD-02). Expanding the table from 17 to 44 entries automatically expands tool name normalization. No code change needed in `guard.py`.

### NORM-05: RTL_OVERRIDES refactor

Replace literal invisible chars with `chr()` calls:

```python
RTL_OVERRIDES = frozenset(
    [
        chr(0x202A),  # LRE
        chr(0x202B),  # RLE
        chr(0x202C),  # PDF
        chr(0x202D),  # LRO
        chr(0x202E),  # RLO
        chr(0x2066),  # LRI
        chr(0x2067),  # RLI
        chr(0x2068),  # FSI
        chr(0x2069),  # PDI
    ]
)
```

Add validation test ensuring all members are strippable (see test plan #15).

## Test plan

### Unit tests — `tests/test_normalize.py`

Class grouping (follows existing pattern): tests 1-2 in `class TestReStripAfterNFKC`, tests 3-5 in `class TestCombiningMarkStrip`, tests 6-14 extend existing `class TestHomoglyph`, tests 15-16 in `class TestRTLOverrides` (new), tests 17-18 in existing `class TestEdgeCases`.

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_nfkc_restrip_no_op_on_clean_input` | ASCII input → no `nfkc_restrip_applied` in transformations |
| 2 | `test_nfkc_restrip_wiring` | Defense-in-depth test: call `_is_strippable()` directly on known Cf chars to verify the filter is wired into the re-strip path. The full `normalize()` pipeline strips all Cf in step 2 before NFKC, so no BMP input naturally reaches step 4 with Cf chars intact (D1 confirms this). This test validates the filter function, not the pipeline path. |
| 3 | `test_combining_mark_stripped_after_nfkc` | "ign" + U+0301 + "ore" → normalized = "ignore"; `combining_marks_stripped` in transformations |
| 4 | `test_combining_mark_precomposed_stripped` | Precomposed "ń" (U+0144) → normalized = "n"; diacritic removed |
| 5 | `test_combining_mark_no_op_ascii` | ASCII input → no `combining_marks_stripped` in transformations |
| 6 | `test_homoglyph_cyrillic_ka_mapped` | Cyrillic к (U+043A) → "k" |
| 7 | `test_homoglyph_cyrillic_kha_mapped` | Cyrillic х (U+0445) → "x" |
| 8 | `test_homoglyph_cyrillic_en_mapped` | Cyrillic н (U+043D) → "h" |
| 9 | `test_homoglyph_uppercase_cyrillic` | Cyrillic А (U+0410) → "A", Е→E, etc. |
| 10 | `test_homoglyph_greek_tau_mapped` | Greek τ (U+03C4) → "t" |
| 11 | `test_homoglyph_greek_uppercase` | Greek Α (U+0391) → "A", etc. |
| 12 | `test_homoglyph_greek_mu` | Greek mu μ (U+03BC) → "u"; also test full pipeline with micro sign U+00B5 input → "u" (NFKC maps to mu first, then homoglyph maps to u) |
| 13 | `test_homoglyph_count_at_least_40` | `len(_HOMOGLYPH_TABLE)` >= 40 |
| 14 | `test_all_original_17_homoglyphs_preserved` | Regression: all 17 original mappings still present |
| 15 | `test_rtl_overrides_all_strippable` | Every char in `RTL_OVERRIDES` returns `_is_strippable(ch) == True` |
| 16 | `test_rtl_overrides_count_unchanged` | `len(RTL_OVERRIDES)` == 9 (same as before refactor) |
| 17 | `test_pipeline_order_strip_nfkc_restrip_mn_homoglyph` | Compound input with Cf + combining mark + Cyrillic confusable → all three transforms applied in correct order |
| 18 | `test_normalize_idempotent_with_mn_strip` | `normalize(normalize(text).normalized).normalized == normalize(text).normalized` for combining mark payloads |

### Adversarial tests — `tests/adversarial/normalization/test_unicode_bypass.py`

| # | Test | Asserts |
|---|------|---------|
| 19 | `test_cyrillic_homoglyph_k_now_mapped` (update existing) | Cyrillic ka (U+043A) IS mapped to 'k' — update assertion from "not mapped" to "mapped" |
| 20 | `test_combining_mark_between_letters_now_stripped` (update existing) | After normalize, "ignore previous instructions" IS recovered — update assertion |
| 21 | `test_nfkc_restrip_defense_in_depth` (new) | Defense-in-depth wiring test: verify that `_is_strippable()` correctly identifies Cf chars that would be caught by the re-strip pass. No BMP input naturally reaches step 4 with Cf intact (D1); this test validates the filter function with synthetic post-NFKC input to guard against future Unicode versions. |

## Test command

```
python -m pytest tests/test_normalize.py tests/adversarial/normalization/test_unicode_bypass.py -v
```

## Done when

- [ ] Re-strip pass after NFKC exists and appends `nfkc_restrip_applied` when active (NORM-02)
- [ ] NFD + Mn strip pass exists after re-strip and appends `combining_marks_stripped` when active (NORM-04)
- [ ] `_HOMOGLYPH_TABLE` has >= 40 mappings covering Cyrillic к/х/н/т/м + uppercase, Greek τ/η/µ + uppercase (NORM-03)
- [ ] `RTL_OVERRIDES` uses `chr()` notation and all members validate as `_is_strippable()` (NORM-05)
- [ ] Combining mark injection "ign" + U+0301 + "ore" → normalized = "ignore"
- [ ] Cyrillic к (U+043A) → "k" in normalized output
- [ ] All 21 tests listed above pass
- [ ] Adversarial tests `test_cyrillic_homoglyph_k_not_mapped` and `test_combining_mark_between_letters` updated to assert fixes
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of scope

- Full Unicode confusables library integration (future, if evasion reports accumulate)
- Normalization of non-Latin scripts beyond confusable mapping (CJK, Arabic, Devanagari)
- NORM-01 / PET-43 (already shipped)
- Regex whitespace flexibility (PET-66 / SYN-02 — complementary, independent)
- Stripping Cc control characters (\n, \r, \t are meaningful whitespace)
- Fullwidth A-Z/a-z in homoglyph table (NFKC already handles all 94 fullwidth ASCII variants)
- Per-character performance optimization (precomputed Cf frozenset — future if profiling shows need)
- `MinimalScanner` encoding finding for combining mark stripping (follow-up: add `petasos.syntactic.encoding.combining-marks` rule)
- `guard.py` `_normalize_tool_name()` NFD + Mn strip (combining mark tool name bypass remains open; follow-up ticket)

## Deferred (P2+)

- **Pipeline gate interaction with D5:** The pipeline's all-or-nothing normalization gate (`pipeline.py` L371-377) means Mn stripping is disabled when ANY normalization toggle is off (e.g., `map_homoglyphs=False`). D5's "unconditional" refers to within `normalize()` — the function always runs all 6 steps. Restructuring the pipeline gate is out of scope.
- **guard.py tool name Mn strip:** `_normalize_tool_name()` does NFKC + homoglyph + casefold but not NFD + Mn strip. A combining mark in a tool name could evade allowlist/blocklist matching. Follow-up ticket recommended.
- **Mn vs Mc/Me boundary:** Only Mn (nonspacing marks) are stripped. Mc (spacing combining marks) and Me (enclosing marks) are preserved. No known attack uses Mc/Me for injection evasion; stripping them would be aggressively lossy without security benefit.
