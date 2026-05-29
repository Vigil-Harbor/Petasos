# Reconciliation Report: PET-36

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-36.spec.md
> Merge: PR #12 (e451cb8); content commits 447a904 + f9f8b31 (whitespace hardening), both reachable from master
> Plane state: Done (group: completed)

## Summary
GUARD-03 alias-onto-exempt smuggling is closed exactly as specified: construction-time `ValueError` in both `_parse_profile` and `_merge_with_base`, plus a profile-introduced-only runtime fallback in `_normalize_tool_name`. All 7 new tests + the updated existing test landed; the current on-disk code is functionally equivalent to the shipped diff with cosmetic deltas (`.lower()` → `.casefold()`, plus NFKC/homoglyph normalization prepended) introduced by the parallel PET-35 unicode merge.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/premium/profiles/__init__.py` | Yes | Non-string value guard + `.strip()` normalization + alias→exempt collision check in both `_parse_profile` (L111-125) and `_merge_with_base` (L206-216). Matches Change 1 & 2. |
| `petasos/premium/guard.py` | Yes | Profile-introduced-only runtime fallback in `_normalize_tool_name` (L181-197). Matches Change 3. |
| `tests/adversarial/guard/test_tool_smuggling.py` | Yes | Updated `test_profile_alias_maps_exec_to_read_exempt` + 2 new (runtime fallback, full-evaluate block) + 1 extra whitespace fallback from f9f8b31. |
| `tests/test_profiles.py` | Yes | Added parse-time + merge-time `ValueError` tests + 2 whitespace variants from f9f8b31. |
| `tests/test_guard.py` | Yes | Added `TestGuard03AliasExempt` with D8, structural invariant, valid-alias tests (L329-352). |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-36.test-output.txt` — CI/mypy artifact (`Success: no issues found in 49 source files`), benign, not source/test logic.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | Defense-in-depth: construction reject AND runtime fallback, same profile-own invariant | Confirmed | Construction: `profiles/__init__.py:119-125`, `:211-216`. Runtime keys on profile-own map only: `guard.py:185-190` (`name in self._profile.tool_alias_map`). |
| D2 | Fall back to un-aliased name, not empty string | Confirmed | `guard.py:196` `resolved = pre_alias` (pre_alias captured at L181); never returns `""`. |
| D3 | Single-hop aliasing; collision check inspects direct targets only | Confirmed | `collisions = {v.casefold() for v in alias_map.values()} & exempt_set` (`profiles/__init__.py:120`, `:212`); no chain chasing. |
| D4 | Construction misconfiguration raises `ValueError`, not silent drop | Confirmed | `profiles/__init__.py:122-125`, `:213-216` raise with `cannot be exempt keys` message naming the profile. |
| D5 | Tests in repo's flat layout, not brief's `tests/unit/premium/` | Confirmed | Tests landed in `tests/test_profiles.py`, `tests/test_guard.py`, `tests/adversarial/guard/test_tool_smuggling.py`; no `tests/unit/premium/` tree created. |
| D6 | Structural invariant enforced by test, not import-time `assert` | Confirmed | `test_default_aliases_not_in_builtin_exempt` at `tests/test_guard.py:335`; no module-load assert in `guard.py`. |
| D7 | Compare alias targets case-insensitively against lowercased exempt set | Confirmed (drifted impl, same intent) | Spec says `.lower()`; on-disk uses `.casefold()` (`profiles/__init__.py:117,120,212`; `guard.py:189`) — equivalent/stronger case-folding from PET-35 merge. f9f8b31 added `.strip()` on both sides, exceeding D7's scope (closes a whitespace-evasion gap the spec did not name). |
| D8 | Default alias landing on operator-exempted target stays legal | Confirmed | Runtime check guarded by `name in self._profile.tool_alias_map` (`guard.py:188`); `test_default_alias_onto_exempt_still_allowed` (`test_guard.py:329`) asserts `normalize("bash")=="exec"`; `test_guard_with_profile_exempt` (`test_premium_integration.py:373`) stays green. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `_parse_profile` raises `ValueError` when alias target ∈ exempt list | Met | `profiles/__init__.py:121-125`; test `tests/test_profiles.py:263`. |
| 2 | `_merge_with_base` raises `ValueError` for same condition | Met | `profiles/__init__.py:211-216`; test `tests/test_profiles.py:283`. |
| 3 | `_normalize_tool_name` falls back to un-aliased name for profile-introduced alias→exempt (default aliases not suppressed) | Met | `guard.py:185-196`; tests `test_alias_onto_exempt_runtime_fallback` (smuggling:95) + D8 `test_default_alias_onto_exempt_still_allowed` (guard:329). |
| 4 | All 7 new tests pass | Met (presence verified) | parse (profiles:263), merge (profiles:283), runtime-fallback (smuggling:95), full-evaluate (smuggling:113), D8 (guard:329), structural (guard:335), valid-alias (guard:349). Plus 3 whitespace tests from f9f8b31. |
| 5 | Existing `test_profile_alias_maps_exec_to_read_exempt` updated to assert `normalize("exec")=="exec"` | Met | `tests/adversarial/guard/test_tool_smuggling.py:79,92` asserts `== "exec"`. |
| 6 | `test_guard_with_profile_exempt` and `test_exempt_tool_skips_scanning` still pass unchanged | Met / Partial | `test_guard_with_profile_exempt` present & unchanged (`test_premium_integration.py:373`). `test_exempt_tool_skips_scanning` does NOT exist by that name in the repo (spec-authoring reference inaccuracy — not a PET-36 deliverable, only required to "stay green"); nearest analog `test_exempt_param_scan_disabled_skips` (smuggling:242) is present. No PET-36-authored artifact affected. |
| 7 | `ruff check`, `ruff format --check`, `mypy --strict` clean; full pytest no regression | Unverifiable | Not re-run here (read-only reconcile). `PET-36.test-output.txt` records a clean mypy run (`no issues found in 49 source files`) at landing. |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| `test_alias_onto_exempt_raises_at_parse` | Yes | tests/test_profiles.py:263 |
| `test_alias_onto_exempt_raises_at_merge` | Yes | tests/test_profiles.py:283 |
| `test_alias_onto_exempt_runtime_fallback` | Yes | tests/adversarial/guard/test_tool_smuggling.py:95 |
| `test_alias_exec_to_read_exempt_blocked` | Yes | tests/adversarial/guard/test_tool_smuggling.py:113 |
| `test_default_alias_onto_exempt_still_allowed` (D8) | Yes | tests/test_guard.py:329 |
| `test_default_aliases_not_in_builtin_exempt` | Yes | tests/test_guard.py:335 |
| `test_valid_alias_still_works` | Yes | tests/test_guard.py:349 |
| `test_profile_alias_maps_exec_to_read_exempt` (updated) | Yes | tests/adversarial/guard/test_tool_smuggling.py:79 |
| `test_tool_alias_map_empty_value_raises` (must stay green; `non-empty` substring retained) | Yes | tests/test_profiles.py:243 |
| `test_guard_with_profile_exempt` (regression guard) | Yes | tests/test_premium_integration.py:373 |
| `test_exempt_tool_skips_scanning` (spec-named regression guard) | No (not in repo by this name) | nearest: tests/adversarial/guard/test_tool_smuggling.py:242 `test_exempt_param_scan_disabled_skips` |
| `test_whitespace_alias_onto_exempt_runtime_fallback` (f9f8b31 extra) | Yes | tests/adversarial/guard/test_tool_smuggling.py:137 |
| `test_alias_onto_exempt_raises_at_parse_whitespace` (f9f8b31 extra) | Yes | tests/test_profiles.py:273 |
| `test_alias_onto_exempt_raises_at_merge_whitespace` (f9f8b31 extra) | Yes | tests/test_profiles.py:293 |

## Wiki-ready
- D1 + D8 boundary: the GUARD-03 fix enforces a *profile-own* invariant on both gates — an alias may not target one of *that profile's own* exempt keys, while a built-in default alias (`bash→exec`) inheriting an operator's exemption of its canonical target stays legal. This profile-own vs. combined-map distinction is the non-obvious, reusable constraint (an earlier draft keyed the runtime check on the combined map and broke legitimate behavior). Constrains any future multi-hop alias work (D3) and any new default-alias additions (guarded by the structural tripwire test).

RECONCILED: yes DRIFT: 1
