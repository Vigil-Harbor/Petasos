# PET-43 — NORM-01: Unicode Tag Character Bypass in normalize()

**Ticket:** PET-43 · **Finding:** NORM-01 · **Priority:** Medium (Urgent via RT-075 chain)
**Parent:** PET-14 · **Blocks:** PET-12 (release), PET-15 (RT-075 chain Link 1)

## Goal

Replace the hand-curated `INVISIBLE_CHARS` frozenset in `normalize.py` with a Unicode-category-based stripping predicate. The `Cf` (Format) category covers the entire Tags block (U+E0001–U+E007F), all bidi controls, joiners, and invisible format characters — a strict superset of every `Cf` character in the current hand-curated set. An `_EXTRA_INVISIBLE` set catches additional invisible-rendering characters outside `Cf` (Braille Pattern Blank, Narrow NBSP). This closes the tag-character insertion bypass (RT-075 Link 1) where an attacker inserts invisible format characters between trigger words to evade injection regex patterns.

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/normalize.py` | Add `_is_strippable()`, `_STRIP_CATEGORIES`, `_EXTRA_INVISIBLE`; refactor strip stage; keep `INVISIBLE_CHARS` |
| `tests/test_normalize.py` | Add 9 tests for category-based stripping, backward compat, safety checks |
| `tests/adversarial/normalization/test_unicode_bypass.py` | Update NORM-01 bypass test; add 2 new post-fix detection tests |
| `tests/adversarial/pipeline/test_rt075_chain.py` | Remove `xfail` from `test_rt075_chain_norm01_breaks_link1` |

### Files to leave alone

- `petasos/scanners/minimal.py` — fix is in the normalizer; once tag chars are stripped, existing injection regexes fire normally
- `petasos/_types.py` — `NormalizedText` dataclass is unchanged
- `petasos/pipeline.py` — `Pipeline.inspect()` already calls `normalize()` before scanning; no changes needed. Note: `PetasosConfig.normalize_nfkc=False` (or other normalize toggles off) causes the pipeline to skip `normalize()` for ML scanner input. This is pre-existing behavior; `MinimalScanner` always normalizes internally regardless of config toggles.

## Design

### D1: Category-based stripping predicate

Add `_STRIP_CATEGORIES`, `_EXTRA_INVISIBLE`, and `_is_strippable()` after the existing imports. The strip stage (L87–93) is refactored to use the predicate.

**`_STRIP_CATEGORIES`** — `frozenset({"Cf"})`. The `Cf` (Format) Unicode General Category covers:

- **Tags block** (U+E0001–U+E007F) — the critical gap this fix closes
- ZWSP (U+200B), ZWNJ (U+200C), ZWJ (U+200D), soft hyphen (U+00AD), BOM (U+FEFF)
- All bidi controls: LRE, RLE, PDF, LRO, RLO, LRI, RLI, FSI, PDI, LRM, RLM
- Word joiner (U+2060), function application (U+2061), invisible times/separator/plus (U+2062–U+2064)
- Mongolian Vowel Separator (U+180E) — reclassified from `Zs` to `Cf` in Unicode 6.3; Python 3.11+ uses Unicode 15.0

This subsumes 21 of the 22 characters in the existing `INVISIBLE_CHARS` frozenset. The lone exception is U+202F (Narrow NBSP), which is `Zs`.

**Expanded Cf surface — Arabic and other scripts.** The `Cf` category includes ~161 codepoints, among them Arabic number signs (U+0600–U+0605), Arabic end-of-ayah (U+06DD), Arabic letter mark (U+061C), and interlinear annotation characters (U+FFF9–U+FFFB). These affect text rendering in legitimate multilingual content. This is an accepted trade-off: Petasos is an injection detector operating on LLM prompts where invisible format characters in injection payloads are more likely adversarial than legitimate. The existing `INVISIBLE_CHARS` already stripped bidi controls that affect Arabic layout. Expanding to all `Cf` is a deliberate widening of the strip surface for security.

**`_EXTRA_INVISIBLE`** — characters that are invisible/blank-rendering but have non-Cf categories:

| Character | Category | Reason |
|-----------|----------|--------|
| U+2800 BRAILLE PATTERN BLANK | `So` | Renders as blank space in most fonts |
| U+202F NARROW NO-BREAK SPACE | `Zs` | Was in `INVISIBLE_CHARS`; NFKC normalizes it to space, but stripping maintains backward-compatible `invisible_chars_stripped` counting |
| U+180E MONGOLIAN VOWEL SEPARATOR | `Cf` | Belt-and-suspenders; `Cf` in modern Unicode but was `Zs` pre-6.3 |

**Brief deviation:** The brief's `_EXTRA_INVISIBLE` contained `{U+2800, U+180E, U+00AD}`. This spec drops U+00AD (soft hyphen) because it is `Cf` and already covered by the category filter — including it was redundant. This spec adds U+202F (Narrow NBSP) because it is the sole `INVISIBLE_CHARS` member with category `Zs`, not `Cf`. Without it, `test_existing_invisible_chars_still_stripped` (test #5) would fail.

**`_is_strippable()`:**

```python
_STRIP_CATEGORIES: frozenset[str] = frozenset({"Cf"})

_EXTRA_INVISIBLE: frozenset[str] = frozenset([
    chr(0x2800),  # BRAILLE PATTERN BLANK (So)
    chr(0x202F),  # NARROW NO-BREAK SPACE (Zs -- was in INVISIBLE_CHARS)
    chr(0x180E),  # MONGOLIAN VOWEL SEPARATOR (Cf -- belt-and-suspenders)
])

def _is_strippable(ch: str) -> bool:
    return unicodedata.category(ch) in _STRIP_CATEGORIES or ch in _EXTRA_INVISIBLE
```

Uses `chr()` calls instead of literal invisible characters for reviewability and diffability, consistent with the adversarial test file pattern (`_TAG = chr(0xE0001)`).

**Strip stage replacement** (replaces L87–93):

```python
# Step 2: Invisible character stripping (category-based)
stripped_count = sum(1 for ch in text if _is_strippable(ch))
if stripped_count > 0:
    text_after_strip = "".join(ch for ch in text if not _is_strippable(ch))
    transforms.append("invisible_chars_stripped")
else:
    text_after_strip = text
```

**Rationale:** `unicodedata.category()` is a C-level lookup in CPython. One predicate covers the entire Tags block (128 chars), all bidi controls, and all future Unicode format characters — no more hand-curation gaps.

### D2: Cf only — not Mn or Cc

The brief's remediation table incorrectly lists variation selectors (U+FE00–U+FE0F, U+E0100–U+E01EF) under `Cf`. Verified: they are `Mn` (Non-spacing Mark). Per the brief's own decision, `Mn` is NORM-04's domain — combining marks require different treatment (NFD decomposition, not simple removal). Control characters (`Cc`) include `\n`, `\r`, `\t` which are meaningful whitespace — stripping them breaks legitimate input.

**Consequence:** The brief's proposed test `test_variation_selectors_stripped` is dropped from this spec's test plan. Variation selectors are out of scope (NORM-04).

### D3: Keep `INVISIBLE_CHARS` unchanged

Keep the existing `INVISIBLE_CHARS` frozenset byte-for-byte unchanged. The adversarial test file imports it (`from petasos.normalize import INVISIBLE_CHARS`). No deprecation annotation is added — the codebase has no deprecation precedent and the repo is pre-release (0.0.1). `INVISIBLE_CHARS` is not exported in `__init__.py`. When v2.0 ships, it can be removed and the adversarial test import updated in the same PR.

### D4: RTL detection order preserved

RTL detection at L82–85 checks `RTL_OVERRIDES & set(text)` on the original text before the strip pass. All RTL override characters are `Cf` and will be stripped in step 2. Detection is unaffected because it runs before stripping. No change needed.

### D5: Strip-before-NFKC order preserved

The strip -> NFKC -> homoglyph pipeline order is correct and unchanged. Stripping format chars before NFKC prevents them from interfering with compatibility decomposition.

### D6: Space-sensitivity and SYN-02 interaction

The existing adversarial test uses `f"ignore{TAG}previous instructions"` where the tag char replaces the space. After stripping, this becomes `"ignoreprevious instructions"` — the injection regex `ignore previous instructions` (literal space) still does not match. This is expected and correct: NORM-01 strips the invisible character; PET-66 (SYN-02) independently addresses flexible whitespace matching in the regex. Together they provide defense-in-depth.

**Brief correction:** The brief's `test_tag_char_injection_now_detected` (brief L126) asserts the injection pattern matches after stripping from `ignore\U000E0001previous instructions` (no space). This is incorrect — the regex at `minimal.py:29` requires a literal space. The spec's test #11 uses a payload WITH a space (`f"ignore {TAG}previous instructions"`) where stripping the tag char correctly restores the trigger phrase.

The RT-075 chain test uses `f"ignore {TAG}previous instructions"` (space before tag char). After stripping: `"ignore previous instructions"` — the regex fires. The `xfail` on `test_rt075_chain_norm01_breaks_link1` should be removed.

### D7: No auto-enable, no silent fix

If format characters are present in input, they are stripped and counted. The fix does not silently swallow misconfigurations — it expands what counts as "invisible" using a principled Unicode category rather than a hand-curated list.

## Test plan

### Unit tests — `tests/test_normalize.py`

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_tag_char_stripped_by_category` | U+E0001 is stripped; result shows `invisible_chars_stripped >= 1` |
| 2 | `test_tag_block_range_stripped` | All `Cf`-category chars in U+E0001–U+E007F are stripped (97 of 127; the 30 unassigned `Cn` codepoints in U+E0002–U+E001F are not stripped) |
| 3 | `test_braille_blank_stripped` | U+2800 stripped via `_EXTRA_INVISIBLE` |
| 4 | `test_mongolian_separator_stripped` | U+180E stripped |
| 5 | `test_existing_invisible_chars_still_stripped` | Regression: every char in current `INVISIBLE_CHARS` returns `_is_strippable(ch) == True` |
| 6 | `test_printable_ascii_not_stripped` | No printable ASCII character (0x20–0x7E) is stripped by `_is_strippable` |
| 7 | `test_cjk_not_stripped` | CJK characters (category `Lo`) are not stripped |
| 8 | `test_whitespace_preserved` | Space (U+0020), tab (U+0009), newline (U+000A) are not stripped |
| 9 | `test_normalize_idempotent_after_fix` | `normalize(normalize(text).normalized).normalized == normalize(text).normalized` for tag-char payloads |

### Adversarial tests — `tests/adversarial/normalization/test_unicode_bypass.py`

| # | Test | Asserts |
|---|------|---------|
| 10 | `test_tag_char_u_e0001_splits_ignore_previous` (update) | Remove `assert _TAG not in INVISIBLE_CHARS` (no longer relevant — stripping is by category). Change `assert _TAG in norm.normalized` to `assert _TAG not in norm.normalized`. Keep scanner assertions: injection regex still misses because no space was present between words (SYN-02 scope). Keep `INVISIBLE_CHARS` import — `test_nbsp_u00a0_not_in_invisible_set_but_nfkc_collapses` still uses it. Update docstring to reflect the fix (tag char is now stripped). |
| 11 | `test_tag_char_with_space_injection_detected` (new) | Pass raw payload `f"ignore {TAG}previous instructions"` to `scanner.scan()`. The scanner internally normalizes, stripping the tag char, restoring `"ignore previous instructions"`, and the `ignore-previous` injection IS detected. |
| 12 | `test_multi_tag_char_injection` (new) | Multiple different tag chars (U+E0001, U+E0020, U+E007F) inserted across a phrase are all stripped by `normalize()` |

### RT-075 chain — `tests/adversarial/pipeline/test_rt075_chain.py`

| # | Test | Asserts |
|---|------|---------|
| 13 | `test_rt075_chain_norm01_breaks_link1` (update) | Remove `@pytest.mark.xfail` — test passes with NORM-01 fix |

## Test command

```
python -m pytest tests/test_normalize.py tests/adversarial/normalization/test_unicode_bypass.py tests/adversarial/pipeline/test_rt075_chain.py -v
```

## Done when

- [ ] `_is_strippable()` predicate added to `normalize.py` using `unicodedata.category()` with `Cf` category
- [ ] `_EXTRA_INVISIBLE` set covers U+2800, U+202F, and U+180E (using `chr()` form)
- [ ] Strip stage refactored to use `_is_strippable()` instead of `INVISIBLE_CHARS` membership
- [ ] `INVISIBLE_CHARS` frozenset preserved unchanged (no deprecation annotation)
- [ ] All 13 tests listed above pass
- [ ] Existing `test_tag_char_u_e0001_splits_ignore_previous` updated to assert tag char IS stripped
- [ ] `test_rt075_chain_norm01_breaks_link1` `xfail` removed
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of scope

- Variation selector stripping (U+FE00–U+FE0F, U+E0100–U+E01EF) — these are `Mn` (Non-spacing Mark), not `Cf`; deferred to NORM-04. The brief's table incorrectly categorized them as `Cf`
- Combining mark stripping (NORM-04 — separate finding, different technique: NFD decomposition)
- Homoglyph table expansion (NORM-03 — separate finding)
- Regex whitespace flexibility (PET-66 / SYN-02 — complementary, independent fix)
- Drawbridge backport (uncoupled; own ticket if needed)
- `INVISIBLE_CHARS` removal (deferred to v2.0 breaking-change window)
- Stripping `Cc` control characters (risk of breaking legitimate input: `\n`, `\r`, `\t`)
- Arabic/multilingual format character preservation (accepted trade-off; see D1)

## Deferred (P2+)

- **chr() vs literal style divergence in normalize.py** — new `_EXTRA_INVISIBLE` uses `chr()` while existing `RTL_OVERRIDES`/`INVISIBLE_CHARS` use literal chars. `chr()` is preferred going forward; converting existing sets is a follow-up.
- **D3 overrides brief's "preserve as deprecated" label** — brief DCF bullet 3 says "preserve as deprecated"; spec D3 says "no deprecation annotation" (pre-release, no precedent). Intentional override.
- **Performance at max payload (512KB)** — `unicodedata.category()` is ~6x slower than frozenset `in` per character. At 512KB (~44ms vs ~7ms), exceeds the 5ms syntactic-only budget. Acceptable: max-payload inputs already trigger oversized-payload finding; typical payloads <10K add <1ms. A precomputed Cf frozenset at module load is a future optimization if needed.
