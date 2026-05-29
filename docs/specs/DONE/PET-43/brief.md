# PET-43 — NORM-01: Unicode Tag Character Bypass in normalize()

**Plane:** PET-43 · **Finding:** NORM-01 · **Priority:** Medium (Urgent via RT-075 chain)  
**OWASP:** ASI01 — Prompt injection  
**Parent:** PET-14 · **Blocks:** PET-12 (release), PET-15 (RT-075 chain Link 1)  
**Status:** refuted → ready-for-dev

---

## Problem

`normalize()` at `petasos/normalize.py:71–115` strips invisible characters via the `INVISIBLE_CHARS` frozenset (L21–46) before NFKC normalization. The set is hand-curated and covers common zero-width characters (ZWSP, ZWNJ, ZWJ, word joiner, bidi controls, etc.) but omits entire Unicode blocks that are invisible to humans yet interpreted by LLMs as meaningful tokens.

The critical gap: **Unicode Tags block (U+E0001–U+E007F)** is absent from `INVISIBLE_CHARS`. An attacker inserts a tag character between trigger words — e.g., `ignore\u{E0001}previous instructions` — and the tag character survives both the strip pass (L88–91) and NFKC normalization (L96, which does not decompose tag chars). The downstream injection regex at `minimal.py:29` (`ignore previous instructions`) never fires because the tag char sits between the words.

This is not theoretical. The existing adversarial test `test_tag_char_u_e0001_splits_ignore_previous` at `tests/adversarial/normalization/test_unicode_bypass.py:20–33` confirms the bypass: the tag character survives normalization unchanged, and the `ignore-previous` injection pattern is not matched.

### Additional missing character classes

The PET-14 security assertion audit (Lens 5) identified several other invisible characters absent from `INVISIBLE_CHARS`:

- **U+E0000–U+E007F** — Tags block (tag characters, invisible to rendering)
- **U+2800** — Braille Pattern Blank (renders as whitespace)
- **U+180E** — Mongolian Vowel Separator (invisible in most fonts)
- **U+FE00–U+FE0F** — Variation Selectors (modify preceding char's glyph)
- **U+E0100–U+E01EF** — Variation Selectors Supplement

All share the same attack surface: inserted between trigger words, they defeat literal-match and `\s+`-based patterns because they are neither stripped nor recognized as whitespace.

## Prior Art

Unicode tag character injection is a well-documented attack vector against LLM security systems. AWS's security blog documents "Unicode character smuggling" where each ASCII character maps to U+E0000 plus its codepoint, producing invisible instructions that LLMs interpret normally. Cisco's AI security research specifically covers tag prompt injection as a bypass for content filters. The Trend Micro research team catalogued invisible prompt injection via tag characters as a distinct threat class in early 2025.

Drawbridge (TypeScript) does not strip tag characters either — its `INVISIBLE_CHARS` equivalent at `clawmoat-drawbridge-sanitizer/src/validation/index.ts` has the same gap. This is a net-new fix for Petasos; Drawbridge tracks its own remediation separately.

## Remediation

### Approach: Unicode category-based stripping

Rather than continuing to enumerate individual codepoints (which is fragile and incomplete), augment the strip pass with a **Unicode General Category filter**. Python's `unicodedata.category()` returns a two-letter category code. The following categories contain characters that are invisible/non-rendering and should be stripped:

| Category | Description | Key characters |
|----------|-------------|----------------|
| `Cf` | Format characters | ZWNJ, ZWJ, bidi controls, **tag characters**, variation selectors |
| `Mn` | Non-spacing combining marks | Combining accents (addressed by NORM-04; included here for completeness) |
| `Cc` | Control characters | NUL, BEL, etc. (except \n, \r, \t which are meaningful whitespace) |

**Primary target for this brief: `Cf` category.** This single category covers the entire Tags block (U+E0001–U+E007F), all variation selectors, soft hyphen, ZWNJ/ZWJ, bidi controls, word joiner, and every other format character. It subsumes most of the existing `INVISIBLE_CHARS` set.

### Changes

**1. `petasos/normalize.py` — add category-based strip (L82–94)**

Add a `_is_strippable()` predicate and refactor the strip stage:

```python
import unicodedata

# Characters in these Unicode categories are stripped.
# Cf = format chars (tags, variation selectors, ZWNJ/ZWJ, bidi, etc.)
_STRIP_CATEGORIES: frozenset[str] = frozenset({"Cf"})

# Explicit additions not covered by category (render as blank/space but
# have category Lo, So, or Zs rather than Cf).
_EXTRA_INVISIBLE: frozenset[str] = frozenset([
    "⠀",  # BRAILLE PATTERN BLANK (So)
    "᠎",  # MONGOLIAN VOWEL SEPARATOR (Cf in Unicode 13+, but was Zs — belt-and-suspenders)
    "­",  # SOFT HYPHEN (Cf — already covered, but kept for explicitness during transition)
])

def _is_strippable(ch: str) -> bool:
    """Return True if the character should be stripped during normalization."""
    return unicodedata.category(ch) in _STRIP_CATEGORIES or ch in _EXTRA_INVISIBLE
```

Replace the existing strip stage (L88–91):

```python
# Step 2: Invisible character stripping (category-based)
stripped_count = sum(1 for ch in text if _is_strippable(ch))
if stripped_count > 0:
    text_after_strip = "".join(ch for ch in text if not _is_strippable(ch))
    transforms.append("invisible_chars_stripped")
else:
    text_after_strip = text
```

**2. `petasos/normalize.py` — preserve `INVISIBLE_CHARS` as deprecated alias**

Keep `INVISIBLE_CHARS` as a frozen export for backward compatibility (external consumers or tests may reference it), but annotate it:

```python
# Deprecated: category-based stripping via _is_strippable() is now primary.
# Retained for backward compatibility. Will be removed in v2.0.
INVISIBLE_CHARS: frozenset[str] = frozenset([...])  # existing set, unchanged
```

**3. `petasos/normalize.py` — preserve `RTL_OVERRIDES` set**

`RTL_OVERRIDES` (L7–19) is used for *detection* (setting `rtl_overrides_detected` in the result), not for stripping. All RTL override characters have category `Cf` and will be stripped by the new category filter. The detection check at L83–85 must run **before** the strip pass (it already does — no change needed).

**4. No changes to `minimal.py`.**

The fix is entirely in the normalizer. Once tag characters are stripped, the trigger phrase `ignore previous instructions` is restored and the existing injection regex at `minimal.py:29` fires normally. The `\s+` fix from PET-66 (SYN-02) is complementary but independent.

### Interaction with other findings

- **PET-15 (RT-075):** This fix breaks Link 1 of the end-to-end bypass chain. The integration test `test_rt075_chain_norm01_breaks_link1` in `tests/adversarial/pipeline/test_rt075_chain.py` should pass after this fix lands.
- **PET-66 (SYN-02):** The `\s+` whitespace fix is complementary. Together, tag char stripping + flexible whitespace matching provide defense-in-depth against inter-word evasion.
- **NORM-04 (combining marks):** Combining marks (category `Mn`) are a separate attack vector with different remediation. This brief does not add `Mn` to `_STRIP_CATEGORIES` — that is NORM-04's scope.
- **NORM-05 (RTL overlap):** The category-based approach subsumes the brittle `RTL_OVERRIDES ∩ INVISIBLE_CHARS` sync issue. Both sets are `Cf`, so the category filter handles them uniformly.

## Tests Required

| Test | File | Asserts |
|------|------|---------|
| `test_tag_char_stripped_by_category` | `tests/test_normalize.py` | U+E0001 is stripped; `_is_strippable("\U000E0001")` returns True |
| `test_tag_block_range_stripped` | `tests/test_normalize.py` | All chars U+E0001–U+E007F are stripped from a payload |
| `test_variation_selectors_stripped` | `tests/test_normalize.py` | U+FE00–U+FE0F and U+E0100–U+E01EF are stripped |
| `test_braille_blank_stripped` | `tests/test_normalize.py` | U+2800 is stripped (explicit `_EXTRA_INVISIBLE`) |
| `test_mongolian_separator_stripped` | `tests/test_normalize.py` | U+180E is stripped |
| `test_existing_invisible_chars_still_stripped` | `tests/test_normalize.py` | Regression: every char in current `INVISIBLE_CHARS` is still stripped by `_is_strippable` |
| `test_printable_ascii_not_stripped` | `tests/test_normalize.py` | No printable ASCII character (0x20–0x7E) is stripped |
| `test_cjk_not_stripped` | `tests/test_normalize.py` | CJK characters (category Lo) are not stripped |
| `test_whitespace_preserved` | `tests/test_normalize.py` | Space, tab, newline are not stripped (category `Zs`/`Cc` but meaningful) |
| `test_tag_char_injection_now_detected` | `tests/adversarial/normalization/test_unicode_bypass.py` | `ignore\U000E0001previous instructions` → after normalize, the `ignore-previous` injection pattern matches |
| `test_multi_tag_char_injection` | `tests/adversarial/normalization/test_unicode_bypass.py` | Multiple different tag chars inserted across an injection phrase are all stripped; pattern matches |
| `test_normalize_idempotent_after_fix` | `tests/test_normalize.py` | `normalize(normalize(text).normalized).normalized == normalize(text).normalized` holds for payloads containing tag chars |

## Decisions Carried Forward

- **Category-based stripping, not set expansion.** Enumerating individual codepoints is a losing game — the Tags block alone has 128 characters, and variation selectors add another 256. `unicodedata.category(ch)` covers current and future Unicode versions in one predicate. The `Cf` category is the correct semantic bucket: "format characters that are not visible but affect text layout."
- **`Cf` only, not `Mn` or `Cc`.** Combining marks (`Mn`) are NORM-04's domain and require different treatment (NFD decomposition + strip, not just removal). Control characters (`Cc`) include `\n`, `\r`, `\t` which are meaningful whitespace — stripping them breaks legitimate input. `Cf` is the surgical choice.
- **Preserve `INVISIBLE_CHARS` as deprecated.** External consumers and existing tests reference it. Removing it is a breaking change deferred to v2.0.
- **Strip before NFKC (existing order preserved).** The current order (strip → NFKC → homoglyph) is correct: stripping format chars before NFKC prevents them from interfering with compatibility decomposition. The category filter changes what gets stripped, not when.
- **No performance concern.** `unicodedata.category()` is a C-level lookup in CPython; the per-character overhead is negligible. The existing strip pass is already O(n) over the input string.

## Done When

- [ ] `_is_strippable()` predicate added to `normalize.py` using `unicodedata.category()` with `Cf` category
- [ ] `_EXTRA_INVISIBLE` set covers U+2800 and U+180E
- [ ] Strip stage refactored to use `_is_strippable()` instead of `INVISIBLE_CHARS` membership
- [ ] `INVISIBLE_CHARS` preserved as deprecated alias
- [ ] All 12 tests listed above pass
- [ ] Existing `test_tag_char_u_e0001_splits_ignore_previous` now demonstrates the fix (tag char stripped, injection detected)
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of Scope

- Combining mark stripping (NORM-04 — separate finding, different technique)
- Homoglyph table expansion (NORM-03 — separate finding)
- Regex whitespace flexibility (PET-66 / SYN-02 — complementary, independent fix)
- Drawbridge backport (uncoupled; own ticket if needed)
- `INVISIBLE_CHARS` removal (deferred to v2.0 breaking-change window)
- Stripping `Cc` control characters (risk of breaking legitimate input)
