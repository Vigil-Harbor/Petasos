# Reconciliation Report: PET-65

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-65.spec.md
> Merge: PR #31 (c3856a6)
> Plane state: Done (group: completed)

## Summary
The shipped commit `c3856a6` implements the spec exactly: `_is_missing_package()` helper extracted into `petasos/scanners/__init__.py`, all three import blocks rewritten to use it with a `_logger.debug()` swallow path, and 11 tests in `tests/test_scanner_init.py`. Current code on disk is byte-for-byte identical to the shipped diff; no drift.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/scanners/__init__.py` | Yes | Helper added, 3 blocks rewritten, `logging` import + `_logger` added. Matches Design §3 final structure exactly (current file L1–49). |
| `tests/test_scanner_init.py` (create) | Yes | New file, 170 lines, 11 tests (4 unit + 7 integration). |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-65.test-output.txt` — captured pytest run (11 passed) added by the ship-spec workflow as PR audit trail. Documentation artifact, not code/spec; no functional drift. Counted as Unexpected per the mechanical rule.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | `debug` level, not `warning` | Confirmed | `__init__.py:28,38,48` all use `_logger.debug(...)`; no `warning`/`warn` calls present. |
| 2 | Helper function, not inline checks | Confirmed | `__init__.py:12-18` defines `_is_missing_package()`; all three blocks call it (`:26`, `:36`, `:46`) — no residual inline `getattr` guards. |
| 3 | No submodule matching — exact top-level name only | Confirmed | `__init__.py:18` `return exc_name in expected_names` (set membership, exact). Test `test_rejects_submodule` (`test_scanner_init.py:37-39`) asserts `name="llm_guard.submodule"` → `False`. |
| 4 | Bare ImportError always re-raises | Confirmed | `__init__.py:16-17` returns `False` when `exc_name is None`. Test `test_rejects_none_name` (`:33-35`) and integration `test_bare_importerror_reraises` (`:86-103`) cover it. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `_is_missing_package()` extracted and used in all three import blocks | Met | Defined `__init__.py:12-18`; used `:26`, `:36`, `:46`. |
| 2 | `_logger.debug()` emitted on every swallowed ImportError | Met | `__init__.py:28,38,48` — one debug call per block on swallow path. |
| 3 | Bare `ImportError("message")` (no name) re-raises in all three blocks | Met | Helper returns `False` for `name is None` (`:16-17`) → shared logic, all blocks `raise`. Integration `test_bare_importerror_reraises` (`:86`) verifies via llm_guard block. |
| 4 | `ImportError(name="unexpected_module")` re-raises in all three blocks | Met | Helper returns `False` for unexpected name (`:18`). `test_broken_extra_reraises` (`:67`) asserts `name="torch"` propagates with `exc_info.value.name == "torch"`. |
| 5 | Submodule `ImportError(name="llm_guard.submodule")` re-raises (not swallowed) | Met | `test_rejects_submodule` (`:37-39`) → `False`, so caller re-raises. |
| 6 | All 11 tests pass | Met | `PET-65.test-output.txt` shows `11 passed in 0.05s`; all 11 functions present on disk (`test_scanner_init.py:25-169`). |
| 7 | `ruff check .`, `ruff format --check .`, `mypy --strict .` clean | Unverifiable | Not re-run in this read-only reconciliation; `test-output.txt` captures only the pytest portion. No code evidence to the contrary (file is type-annotated, `# noqa: F401` present where needed). |
| 8 | No regression in `pytest` full suite | Met | `PET-65.test-output.txt` includes a full-suite run after the targeted file (all dots/`s`/`x`, no `F`/`E`). |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| `test_is_missing_package_matches_expected_name` | Yes (renamed) | `tests/test_scanner_init.py:25` `TestIsMissingPackage::test_matches_expected_name` |
| `test_is_missing_package_rejects_unexpected_name` | Yes (renamed) | `tests/test_scanner_init.py:29` `::test_rejects_unexpected_name` |
| `test_is_missing_package_rejects_none_name` | Yes (renamed) | `tests/test_scanner_init.py:33` `::test_rejects_none_name` |
| `test_is_missing_package_rejects_submodule` | Yes (renamed) | `tests/test_scanner_init.py:37` `::test_rejects_submodule` |
| `test_broken_extra_reraises` | Yes | `tests/test_scanner_init.py:67` |
| `test_bare_importerror_reraises` | Yes | `tests/test_scanner_init.py:86` |
| `test_missing_extra_removes_from_all` | Yes | `tests/test_scanner_init.py:105` |
| `test_missing_extra_logs_debug` | Yes | `tests/test_scanner_init.py:120` |
| `test_missing_presidio_removes_both_from_all` | Yes | `tests/test_scanner_init.py:137` |
| `test_missing_llama_removes_from_all` | Yes | `tests/test_scanner_init.py:153` |
| `test_minimal_always_present` | Yes | `tests/test_scanner_init.py:168` |

Note: the four unit tests live under class `TestIsMissingPackage` with short method names (e.g. `test_matches_expected_name`); the spec's table used the unqualified `test_is_missing_package_*` form. The class-qualified node IDs are equivalent — same assertions, same coverage. Not counted as drift.

## Wiki-ready
- None — routine hardening fix. The four decisions are localized to one file's import-guard pattern and are fully captured by the spec; nothing constraining or reusable beyond this module.

RECONCILED: yes DRIFT: 1
