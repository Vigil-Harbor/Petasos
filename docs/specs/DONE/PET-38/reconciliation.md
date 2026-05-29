# Reconciliation Report: PET-38

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-38.spec.md
> Merge: PR #23 (squash 9e4c0bb, merge commit e6390fe)
> Plane state: Done (group: completed)

## Summary
PET-38 shipped exactly as specified: `safe_json_dumps` hardens `_scan_params` against circular/deep/oversized tool params, with an aggregate size cap and a catch-all enforcing the never-throws invariant. Current code on disk matches the spec and diff line-for-line; all 13 named tests exist and all acceptance criteria are met.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/premium/_safe_json.py` (create) | Yes | New file, 57 lines; matches spec design verbatim (`_safe_json.py:1-57`). |
| `tests/test_safe_json.py` (create) | Yes | New file, 9 unit tests (`test_safe_json.py:9-68`). |
| `petasos/premium/guard.py` (modify) | Yes | `import json` removed; `safe_json_dumps` imported (`guard.py:11`); `_MAX_PARAM_TEXT_LEN` const (`guard.py:40`); `_scan_params` catch-all (`guard.py:219-261`). |
| `tests/adversarial/guard/test_tool_smuggling.py` (modify) | Yes | 3 adversarial tests appended (`:159,177,196`). |
| `tests/test_guard.py` (modify) | Yes | `TestScanParamsCatchAll` appended (`:522-523`). |
| `petasos/config.py` (leave alone) | Not in diff | Correct — confirmed no depth/size/safe-json fields added. |
| `petasos/pipeline.py` (leave alone) | Not in diff | Correct — no changes. |
| `petasos/premium/alerting.py`, `audit.py` (leave alone) | Not in diff | Correct — `_safe_json` not wired in (deferred). |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-38.test-output.txt` — test-run audit artifact produced by the ship workflow, not a spec-named change. Documentation/evidence only; not code drift.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | New utility file, not inline | Confirmed | `petasos/premium/_safe_json.py:12` defines `safe_json_dumps`; imported into guard at `guard.py:11`. |
| D2 | `set[int]` for seen tracking, not `WeakSet` | Confirmed | `_safe_json.py:21` `seen: set[int] = set()`; `id()` add/`discard` in `finally` at `:33-37,42-46`. |
| D3 | `((), True)` on catch-all, not `allowed=False` | Confirmed | `guard.py:259-261` `except Exception: ... return (), True` inside `_scan_params`; `evaluate()` makes the allow/block call. |
| D4 | Hardcoded depth (32) and size (1 MB) limits, not config | Confirmed | `_safe_json.py:8-9` `_DEFAULT_MAX_DEPTH = 32`, `_DEFAULT_MAX_SIZE = 1_000_000`; `guard.py:40` `_MAX_PARAM_TEXT_LEN = 1_000_000`; config.py has no such fields. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `_safe_json.py` exists with `safe_json_dumps` | Met | `petasos/premium/_safe_json.py:12-17`. |
| 2 | `_scan_params` uses `safe_json_dumps` not `json.dumps` | Met | `guard.py:230` `parts.append(safe_json_dumps(value))`; `import json` absent (grep: no match). |
| 3 | `_scan_params` has catch-all returning `((), True)` | Met | `guard.py:219` try wraps whole body; `:259-261` returns `(), True`. |
| 4 | Total param text capped at 1 MB with truncation + warning log | Met | `guard.py:236-243` length check, `_logger.warning`, slice to `_MAX_PARAM_TEXT_LEN`. |
| 5 | All tests in test command pass (13 new + existing) | Met | `PET-38.test-output.txt` records 60 passed; all 13 named tests present on disk. |
| 6 | `ruff check`, `ruff format --check`, `mypy --strict` clean | Unverifiable | Not re-run in this read-only pass; test-output.txt covers pytest only. No evidence of failure. |
| 7 | No regression in full `pytest` suite | Unverifiable | Not re-run here; shipped test-output shows 60 passed in the targeted run. |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| `test_normal_dict` | Yes | `tests/test_safe_json.py:9` |
| `test_circular_dict` | Yes | `tests/test_safe_json.py:15` |
| `test_circular_list` | Yes | `tests/test_safe_json.py:22` |
| `test_depth_limit` | Yes | `tests/test_safe_json.py:29` |
| `test_unserializable_type` | Yes | `tests/test_safe_json.py:36` |
| `test_size_cap` | Yes | `tests/test_safe_json.py:40` |
| `test_dag_shared_node_not_circular` | Yes | `tests/test_safe_json.py:46` |
| `test_mixed_types` | Yes | `tests/test_safe_json.py:54` |
| `test_never_throws` | Yes | `tests/test_safe_json.py:68` |
| `test_circular_dict_no_crash` | Yes | `tests/adversarial/guard/test_tool_smuggling.py:159` |
| `test_deeply_nested_dict_no_crash` | Yes | `tests/adversarial/guard/test_tool_smuggling.py:177` |
| `test_large_params_truncated` | Yes | `tests/adversarial/guard/test_tool_smuggling.py:196` |
| `test_scan_params_exception_returns_unsafe` | Yes | `tests/test_guard.py:523` (class `TestScanParamsCatchAll:522`) |

## Wiki-ready
- None — routine hardening fix. The `safe_json_dumps` utility (circular/depth/size-safe stringification mirroring Drawbridge `safeStringify`) and the never-throws catch-all pattern returning `((), True)` so the caller arbitrates allow/block are sound, but they restate existing Petasos invariants rather than establish new constraining decisions.

RECONCILED: yes DRIFT: 0
