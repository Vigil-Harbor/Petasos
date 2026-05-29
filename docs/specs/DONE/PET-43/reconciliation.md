# Reconciliation Report: PET-43

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-43.spec.md
> Merge: #35 (4941c3f)
> Plane state: Done (group: completed)

## Summary
The category-based Unicode stripping fix (NORM-01) shipped exactly as specified: `_is_strippable()` with the `Cf` category plus `_EXTRA_INVISIBLE` (U+2800, U+202F, U+180E) replaced the `INVISIBLE_CHARS`-membership strip stage, `INVISIBLE_CHARS` is byte-for-byte unchanged, all 13 named tests exist, and the RT-075 Link-1 `xfail` was removed. No drift — the only diff addition beyond spec scope is a benign test-output transcript file.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/normalize.py` | Yes | Added `_STRIP_CATEGORIES`, `_EXTRA_INVISIBLE`, `_is_strippable()`; strip stage refactored (normalize.py:48-60, 134-140). `INVISIBLE_CHARS` kept unchanged. |
| `tests/test_normalize.py` | Yes | Added `TestCategoryBasedStripping` with 9 tests (test_normalize.py:140-194). |
| `tests/adversarial/normalization/test_unicode_bypass.py` | Yes | Updated NORM-01 bypass test; added 2 new detection tests (lines 20, 39, 51). |
| `tests/adversarial/pipeline/test_rt075_chain.py` | Yes | Removed `@pytest.mark.xfail` from `test_rt075_chain_norm01_breaks_link1` (now line 61, no marker). |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-43.test-output.txt` — pytest transcript artifact captured for the PR audit trail (paths redacted in a follow-up commit). Documentation/evidence file, not code; benign.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | Category-based stripping predicate (`Cf` + `_EXTRA_INVISIBLE`), strip-stage refactor using chr() form | Confirmed | normalize.py:48-60 (`_STRIP_CATEGORIES = frozenset({"Cf"})`, `_EXTRA_INVISIBLE` with `chr(0x2800)`/`chr(0x202F)`/`chr(0x180E)`, `_is_strippable`); normalize.py:135-137 strip stage uses `_is_strippable(ch)`. Spec deviation (drop U+00AD, add U+202F) honored. |
| D2 | `Cf` only — not `Mn` or `Cc` | Confirmed | `_STRIP_CATEGORIES` is exactly `frozenset({"Cf"})` (normalize.py:48). No variation-selector test present; `test_variation_selectors_stripped` correctly dropped. |
| D3 | Keep `INVISIBLE_CHARS` unchanged, no deprecation annotation | Confirmed | normalize.py:21-46 frozenset identical to pre-commit (diff shows no edits inside the set, only context line); no deprecation comment added. Adversarial test still imports it (test_unicode_bypass.py). |
| D4 | RTL detection order preserved (before strip) | Confirmed | normalize.py:130-132 RTL detection runs before the strip stage at 135-140; unchanged by the commit. |
| D5 | Strip-before-NFKC order preserved | Confirmed | normalize.py:135 (strip) precedes 143 (NFKC). Order unchanged. |
| D6 | Space-sensitivity / SYN-02 interaction (no-space tag still misses; space+tag detected) | Confirmed | test_unicode_bypass.py:20 asserts no-space payload still misses `ignore-previous`; line 39 `test_tag_char_with_space_injection_detected` asserts space+tag IS detected. |
| D7 | No auto-enable / no silent fix (stripped + counted) | Confirmed | normalize.py:136-138 increments `stripped_count` and appends `invisible_chars_stripped` transform when chars present. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `_is_strippable()` predicate using `unicodedata.category()` with `Cf` | Met | normalize.py:59-60 |
| 2 | `_EXTRA_INVISIBLE` covers U+2800, U+202F, U+180E (chr() form) | Met | normalize.py:50-56 |
| 3 | Strip stage uses `_is_strippable()` not `INVISIBLE_CHARS` membership | Met | normalize.py:135-137 |
| 4 | `INVISIBLE_CHARS` preserved unchanged (no deprecation annotation) | Met | normalize.py:21-46; diff shows no change inside the set |
| 5 | All 13 tests pass | Met | All 13 names exist (test_normalize.py:142-194; test_unicode_bypass.py:20/39/51; rt075:61); transcript PET-43.test-output.txt records passing run |
| 6 | `test_tag_char_u_e0001_splits_ignore_previous` updated to assert tag char IS stripped | Met | test_unicode_bypass.py:30 `assert _TAG not in norm.normalized`; line 31 `invisible_chars_stripped >= 1` |
| 7 | `test_rt075_chain_norm01_breaks_link1` xfail removed | Met | test_rt075_chain.py:60-61 — no `@pytest.mark.xfail` above the test (remaining xfails at L44/L100 belong to other tests) |
| 8 | `ruff check .` and `mypy --strict .` clean | Unverifiable | Read-only reconciliation; follow-up commit applied ruff formatting to test_normalize.py per commit message. Not re-run here. |
| 9 | No regression in full `pytest` suite | Unverifiable | Read-only; transcript records the scoped + suite run passing, but not independently re-executed. |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| `test_tag_char_stripped_by_category` | Yes | tests/test_normalize.py:142 |
| `test_tag_block_range_stripped` | Yes | tests/test_normalize.py:150 |
| `test_braille_blank_stripped` | Yes | tests/test_normalize.py:161 |
| `test_mongolian_separator_stripped` | Yes | tests/test_normalize.py:167 |
| `test_existing_invisible_chars_still_stripped` | Yes | tests/test_normalize.py:173 |
| `test_printable_ascii_not_stripped` | Yes | tests/test_normalize.py:177 |
| `test_cjk_not_stripped` | Yes | tests/test_normalize.py:182 |
| `test_whitespace_preserved` | Yes | tests/test_normalize.py:187 |
| `test_normalize_idempotent_after_fix` | Yes | tests/test_normalize.py:192 |
| `test_tag_char_u_e0001_splits_ignore_previous` (update) | Yes | tests/adversarial/normalization/test_unicode_bypass.py:20 |
| `test_tag_char_with_space_injection_detected` (new) | Yes | tests/adversarial/normalization/test_unicode_bypass.py:39 |
| `test_multi_tag_char_injection` (new) | Yes | tests/adversarial/normalization/test_unicode_bypass.py:51 |
| `test_rt075_chain_norm01_breaks_link1` (xfail removed) | Yes | tests/adversarial/pipeline/test_rt075_chain.py:61 |

## Wiki-ready
- None — routine hardening fix. (Note: the principled "strip by Unicode `Cf` category instead of hand-curated codepoint sets" approach is mildly reusable, but it is already fully documented in the spec/brief decisions and was the predictable remediation for NORM-01.)

RECONCILED: yes DRIFT: 1
