# Reconciliation Report: PET-37

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-37.spec.md
> Merge: PR #38 (380cda0)
> Plane state: Done (group: completed)

## Summary
The PET-37 + PET-58 fixes shipped exactly as specced: exempt tools now scan params and return `allowed=True` with findings (`reason="exempt-with-scan"`), and `ProfileResolver.register()` rejects built-in names via a frozenset guard. All decisions confirmed and every acceptance criterion met; the only drift is one extra existing-test update (`tests/test_profiles.py`) that the spec's scope table omitted but the spec/brief intent required.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/premium/guard.py` | Yes | `exempt_param_scan` ctor param added (guard.py:77-84); Step 4 split into bypass vs scan paths (guard.py:120-137). Matches spec verbatim. |
| `petasos/premium/profiles/__init__.py` | Yes | `_BUILTIN_NAMES` → frozenset (L75-81); `register()` ValueError guard (L256-258). Matches spec. |
| `tests/test_guard.py` | Yes | `test_exempt_tool_skips_scanning` renamed to `test_exempt_tool_scans_params_by_default`, assertions flipped (L302). |
| `tests/test_premium_integration.py` | Yes | `test_guard_with_profile_exempt` reason→`exempt-with-scan` + findings assert (L373). Diff also swapped param `rm -rf /`→`ignore previous instructions` (not flagged in spec prose, but consistent with intent). |
| `tests/adversarial/guard/test_tool_smuggling.py` | Yes | 4 new GUARD-04 tests added (L216, L242, L270, L296). |
| `tests/adversarial/profiles/test_suppress_bypass.py` | Yes | 4 new PROF-03 tests added (L39, L60, L82, L103). |

Unexpected files in diff (not in spec scope table):
- `tests/test_profiles.py` — `test_register_overwrites_existing` renamed to `test_register_builtin_raises` and inverted to assert `register("general", ...)` now raises ValueError. Necessary collateral (the old test asserted the now-forbidden overwrite behavior); the spec scope table missed it. Counts as drift (Unexpected).
- `docs/specs/TODO/PET-37.test-output.txt` — test-run artifact captured for the PR audit trail; not a code/test change. Doc artifact, not counted as functional drift.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | `exempt_param_scan` on guard ctor, not on `PetasosConfig` | Confirmed | `petasos/premium/guard.py:77-78` keyword-only ctor param; no `config.py` change in diff. |
| D2 | Exempt tools always allowed, scan informational; reason `exempt-with-scan` (scan) vs `tool exempt per profile` (bypass) | Confirmed | `petasos/premium/guard.py:122-137` — both paths return `allowed=True`; reason strings exactly as specced. |
| D3 | `_BUILTIN_NAMES` tuple → frozenset | Confirmed | `petasos/premium/profiles/__init__.py:75` `frozenset[str]`. |
| D4 | Hard reject (ValueError) on built-in names, message `"Cannot overwrite built-in profile '{name}'"` | Confirmed | `petasos/premium/profiles/__init__.py:256-258`. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Exempt tool + dangerous params → `allowed=True`, findings populated | Met | guard.py:130-136; `test_exempt_tool_malicious_params_detected` (test_tool_smuggling.py:216). |
| 2 | `exempt_param_scan=False` preserves old behavior (full bypass, empty findings) | Met | guard.py:122-129; `test_exempt_param_scan_disabled_skips` (test_tool_smuggling.py:242). |
| 3 | `register("general", ...)` raises ValueError | Met | profiles/__init__.py:256-258; `test_register_general_raises` (test_suppress_bypass.py:39), `test_register_builtin_raises` (test_profiles.py:168). |
| 4 | `register("my_custom", ...)` succeeds — custom names unrestricted | Met | `test_register_custom_name_succeeds` (test_suppress_bypass.py:82). |
| 5 | Overwriting a custom profile is allowed | Met | `test_register_overwrite_custom_allowed` (test_suppress_bypass.py:103). |
| 6 | Exempt scan findings available on `GuardResult.findings` (no audit.py change) | Met | guard.py:131-136 attaches `findings`; no `audit.py` in diff. |
| 7 | `_BUILTIN_NAMES` is frozenset, not tuple | Met | profiles/__init__.py:75. |
| 8 | 8 new tests + 2 existing updated | Met (exceeded) | 8 new tests confirmed; 3 existing tests updated (test_guard.py, test_premium_integration.py, plus test_profiles.py — one more than the "2" stated). |
| 9 | `ruff check .` and `mypy --strict .` clean | Unverifiable | Read-only reconciliation; not re-run here. PET-37.test-output.txt in diff records a green run. |
| 10 | No regression in full `pytest` suite | Unverifiable | Not re-run; test-output artifact indicates passing run at merge. |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| `test_exempt_tool_scans_params_by_default` | Yes | tests/test_guard.py:302 |
| `test_guard_with_profile_exempt` (updated) | Yes | tests/test_premium_integration.py:373 |
| `test_register_builtin_raises` (updated) | Yes | tests/test_profiles.py:168 |
| `test_exempt_tool_malicious_params_detected` | Yes | tests/adversarial/guard/test_tool_smuggling.py:216 |
| `test_exempt_param_scan_disabled_skips` | Yes | tests/adversarial/guard/test_tool_smuggling.py:242 |
| `test_exempt_clean_params_no_findings` | Yes | tests/adversarial/guard/test_tool_smuggling.py:270 |
| `test_exempt_param_scan_error_marks_unsafe` | Yes | tests/adversarial/guard/test_tool_smuggling.py:296 |
| `test_register_general_raises` | Yes | tests/adversarial/profiles/test_suppress_bypass.py:39 |
| `test_register_all_builtins_raises` | Yes | tests/adversarial/profiles/test_suppress_bypass.py:60 |
| `test_register_custom_name_succeeds` | Yes | tests/adversarial/profiles/test_suppress_bypass.py:82 |
| `test_register_overwrite_custom_allowed` | Yes | tests/adversarial/profiles/test_suppress_bypass.py:103 |

## Wiki-ready
- Decision D1: `exempt_param_scan` lives on `ToolCallGuard.__init__` (keyword-only), not `PetasosConfig` — a deliberate parallelism-contract choice (config.py is Brief 3 territory) that also reads as semantically cleaner. Constraining for future config-surface work (the P2 deferral notes config.py could absorb it post-Brief-3).
- Decision D2: exempt tools are *never* blocked on param-scan findings — the scan is informational only and routes through `Pipeline.inspect()`, so malicious content in exempt-tool params still feeds session frequency/escalation. Non-obvious security-boundary semantics worth recording.

RECONCILED: yes DRIFT: 1
