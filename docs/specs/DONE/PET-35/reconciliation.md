# Reconciliation Report: PET-35

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-35.spec.md
> Merge: PR #27 (b2add64)
> Plane state: Done (group: completed)

## Summary

PET-35 shipped exactly as specified: `_normalize_tool_name` was rewritten with the strip → NFKC → homoglyph → casefold → namespace-strip → alias-lookup order, GUARD-03 preserved with `casefold()`, the 4 profiles `.lower()` → `.casefold()` swaps applied, and all 9 new + 2 updated tests present on disk. No drift.

## Scope

| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/premium/guard.py` | Yes | `import unicodedata` + `from petasos.normalize import _HOMOGLYPH_TABLE` added; `_normalize_tool_name` rewritten (current L171–197); GUARD-03 check uses `casefold()`; returns `resolved.strip().casefold()` |
| `petasos/premium/profiles/__init__.py` | Yes | 4 `.lower()` → `.casefold()` swaps at current L117, L120, L199, L212; zero `.lower()` remaining |
| `tests/adversarial/guard/test_tool_smuggling.py` | Yes | Whitespace test renamed + reasserted; 4 new smuggling tests added |
| `tests/test_guard.py` | Yes | `test_whitespace_stripped` assertion updated to `"read"`; 5 new normalization tests added |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-35.test-output.txt` — captured pytest output for the PR audit trail (added by the ship workflow, not named in the spec scope table). Non-code, non-functional; informational drift only.

## Decisions

| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | Reuse `_HOMOGLYPH_TABLE`, no shared module extraction | Confirmed | guard.py:10 `from petasos.normalize import _HOMOGLYPH_TABLE`; no `petasos/_unicode.py` created |
| 2 | `casefold()` over `lower()` | Confirmed | guard.py:175,189,197 use `.casefold()`; profiles L117/120/199/212 use `.casefold()` |
| 3 | Strip before alias, not after | Confirmed | guard.py:172 `name = tool_name.strip()` is first op; test_guard.py:118 asserts `"  read_file  "` → `"read"` (alias resolves) |
| 4 | `unicodedata` import at module level | Confirmed | guard.py:5 `import unicodedata` in stdlib block (after `re`, before `from dataclasses`) |
| 5 | Preserve GUARD-03 defense | Confirmed | guard.py:183–196 GUARD-03 block intact, gated on `name in self._profile.tool_alias_map` and `resolved.strip().casefold() in tool_exempt_list` |
| 6 | Harmonize profiles `.lower()` → `.casefold()` (4 sites) | Confirmed | profiles/__init__.py:117,120,199,212 all `.casefold()`; grep for `.lower()` returns 0 matches |
| 7 | Alias-key casefolding deferred | Confirmed | No key-side casefolding added; alias maps still keyed as-is (profiles L114 `{k: v.strip() ...}` only strips values) — deferral honored |
| 8 | Casefold after alias resolution | Confirmed | guard.py:197 `return resolved.strip().casefold()` normalizes resolved alias value |

## Acceptance Criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `_normalize_tool_name` applies strip → NFKC → homoglyph → casefold before namespace strip + alias | Met | guard.py:172–182 in exact order |
| 2 | `_HOMOGLYPH_TABLE` imported from `petasos.normalize` | Met | guard.py:10; symbol exists at normalize.py:63 |
| 3 | `unicodedata` imported at module level | Met | guard.py:5 |
| 4 | GUARD-03 alias→exempt defense preserved with `casefold()` | Met | guard.py:183–196, comparison at L189 uses `.casefold()` |
| 5 | profiles 4 `.lower()` → `.casefold()` swaps | Met | profiles L117,120,199,212; zero `.lower()` remain |
| 6 | All 9 new tests pass | Met (existence verified) | smuggling: L35,46,57,68 (+ renamed L24); guard: L148,152,156,160,164; PET-35.test-output.txt records passing run |
| 7 | 2 existing tests updated to match new behavior | Met | smuggling L24 renamed to `..._before_alias_resolves` asserting `"exec"`; guard L117 asserts `"read"` |
| 8 | All existing GUARD-03 tests pass without modification | Met | GUARD-03 logic unchanged (only `.lower()`→`.casefold()`, ASCII no-op); test-output.txt shows full guard suite green |
| 9 | `ruff check .` and `mypy --strict .` clean | Unverifiable | Not re-run here (read-only reconcile); no lint/type artifacts in diff to contradict |
| 10 | No regression in `pytest` full suite | Unverifiable | Full suite not re-run; PET-35.test-output.txt covers the two targeted files only |

## Test Plan

| Test | Exists? | Location |
|---|---|---|
| `test_whitespace_stripped_before_alias_resolves` | Yes | tests/adversarial/guard/test_tool_smuggling.py:24 |
| `test_cyrillic_a_in_bash_normalizes` | Yes | tests/adversarial/guard/test_tool_smuggling.py:35 |
| `test_fullwidth_bash_normalizes` | Yes | tests/adversarial/guard/test_tool_smuggling.py:46 |
| `test_mixed_script_shell_normalizes` | Yes | tests/adversarial/guard/test_tool_smuggling.py:57 |
| `test_invisible_chars_not_stripped` | Yes | tests/adversarial/guard/test_tool_smuggling.py:68 |
| `test_whitespace_stripped` (updated → `"read"`) | Yes | tests/test_guard.py:117 |
| `test_casefold_not_just_lower` | Yes | tests/test_guard.py:148 |
| `test_namespace_prefix_with_cyrillic` | Yes | tests/test_guard.py:152 |
| `test_plain_ascii_no_regression` | Yes | tests/test_guard.py:156 |
| `test_empty_string_normalizes` | Yes | tests/test_guard.py:160 |
| `test_whitespace_only_normalizes` | Yes | tests/test_guard.py:164 |

## Wiki-ready

- None — routine defense-in-depth hardening. The one mildly reusable note is that tool-name normalization is a separate code path from content `normalize()` and intentionally does NOT strip invisible/zero-width chars (documented by `test_invisible_chars_not_stripped` as a deliberate scope boundary). Decisions 7/8 (deferred alias-key casefolding; casefold-after-alias) are spec-local follow-up flags, not standalone wiki entries.

RECONCILED: yes DRIFT: 0
