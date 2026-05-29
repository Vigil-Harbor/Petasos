# Reconciliation Report: PET-57

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-57.spec.md
> Merge: PR #30 (bd02899)
> Plane state: Done (group: completed)

## Summary
PET-57 shipped exactly as specified: `_parse_profile` now wraps `dict(...)` copies around both `severity_overrides` and `tool_alias_map` before `MappingProxyType`, breaking the retained-reference link. All three regression tests exist and pass. The only "extra" file in the diff is the standard PET-57.test-output.txt audit artifact.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/premium/profiles/__init__.py` | Yes | Both `MappingProxyType(dict(...))` copies present — `severity_overrides` at `__init__.py:134`, `tool_alias_map` at `__init__.py:139`. (Spec cited L113/L118; actual current lines are L134/L139 — citation drift only, substance matches.) |
| `tests/test_profiles_retained_ref.py` (new) | Yes | Created with all 3 named tests (`test_profiles_retained_ref.py:10,22,34`). |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-57.test-output.txt` — test-run audit artifact added by the ship workflow, not a code/spec change. Not drift.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | Shallow `dict()` copy is sufficient (str->str maps); follows `PetasosConfig.__post_init__` pattern | Confirmed | `profiles/__init__.py:134,139` use shallow `dict(...)`; `config.py:196` uses identical `MappingProxyType(dict(self.frequency_weights))` pattern (spec cited config.py:193 — off by 3, immaterial). |
| 2 | `_merge_with_base` already safe — no change | Confirmed | `profiles/__init__.py:154` `severity = dict(base.severity_overrides)` and `:201` `alias = dict(base.tool_alias_map)` construct fresh dicts before wrapping; `_merge_with_base` untouched in diff. (Spec cited L133/L178; actual L154/L201.) |
| 3 | Built-in profiles not affected (`_load_builtins` feeds `json.loads` output) — no change | Confirmed | `_load_builtins` not in diff; `_parse_profile` change is defense-in-depth, builtins use ephemeral json dicts. |
| 4 | `alias_map` copy is defense-in-depth (L98 comprehension already creates fresh dict) | Confirmed | `profiles/__init__.py:115` comprehension `{k: v.strip() for k, v in alias_map.items()}` already returns a fresh dict; the `dict(alias_map)` wrap at `:139` is redundant-but-intentional. (Spec cited L98; actual L115.) |
| 5 | Fix is defense-in-depth — public API path (`ProfileResolver.resolve`→`_merge_with_base`) already safe | Confirmed | Public path dispatches to `_merge_with_base` (already safe, Decision 2); `_parse_profile` reachable only by direct/private callers (test code + downstream integrators). Fix applied regardless. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `_parse_profile` wraps `dict(...)` around `severity_overrides` before `MappingProxyType` | Met | `profiles/__init__.py:134` `severity_overrides=MappingProxyType(dict(sev_overrides))` |
| 2 | `_parse_profile` wraps `dict(alias_map)` before `MappingProxyType` for `tool_alias_map` | Met | `profiles/__init__.py:139` `tool_alias_map=MappingProxyType(dict(alias_map))` |
| 3 | `tests/test_profiles_retained_ref.py` exists and passes — all three cases | Met | File on disk with `test_severity_overrides_not_mutated_by_caller`, `test_tool_alias_map_not_mutated_by_caller`, `test_empty_overrides_not_shared`; test-output.txt shows all 3 PASSED. |
| 4 | `mypy --strict petasos/premium/profiles/__init__.py` passes | Met | test-output.txt: "Success: no issues found in 1 source file". (Commit's second sub-commit fixed bare `dict` annotations to `dict[str, Any]` to satisfy strict mode.) |
| 5 | Existing `test_profiles.py` suite still green | Met | test-output.txt: 41 passed (3 new + 38 existing profiles tests). |
| 6 | `ruff check .` and `ruff format --check .` clean | Met | test-output.txt: "All checks passed!" and "60 files already formatted". |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| `test_severity_overrides_not_mutated_by_caller` | Yes | tests/test_profiles_retained_ref.py:10 |
| `test_tool_alias_map_not_mutated_by_caller` | Yes | tests/test_profiles_retained_ref.py:22 |
| `test_empty_overrides_not_shared` | Yes | tests/test_profiles_retained_ref.py:34 |
| Existing `tests/test_profiles.py` (regression-green) | Yes | tests/test_profiles.py (38 tests, all green per test-output.txt) |

## Wiki-ready
- None — routine hardening fix (defensive `dict()` copy before `MappingProxyType` to enforce the frozen-export invariant). The `MappingProxyType(dict(...))` pattern is already established in `config.py`; this fix propagates it to `_parse_profile`.

RECONCILED: yes DRIFT: 0
