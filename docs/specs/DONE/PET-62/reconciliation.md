# Reconciliation Report: PET-62

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-62.spec.md
> Merge: PR #20 (3bd95ee)
> Plane state: Done (group: completed)

## Summary
PET-62 shipped exactly as specified: `LlamaFirewallScanner.scan()` now returns `ScanResult(error="all components disabled — no ML inspection performed")` when zero components are enabled after a successful load, and `_ensure_loaded()` logs a WARNING in that case. All four spec'd tests exist and the on-disk code matches the merged commit.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/scanners/llama_firewall.py` | Yes | Added `import logging` + `_logger`, warning in `_ensure_loaded()` (L98–102), error string on empty-components return (L178). |
| `tests/test_llama_firewall_scanner.py` | Yes | Updated `test_no_components_enabled` assertion; added 3 new tests. |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-62.test-output.txt` — test-output audit artifact added by the ship workflow; not a code/spec change. Benign.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | Error string on empty-components path | Confirmed | `petasos/scanners/llama_firewall.py:172-179` — `if not self._components:` returns `ScanResult(..., error="all components disabled — no ML inspection performed")`. Pipeline consumes it: `petasos/pipeline.py:123,127,137` (`r.error is not None` → `ml_errored`; `all_ml_failure`). |
| D2 | Warning log in `_ensure_loaded()` (NOT constructor) | Confirmed | `petasos/scanners/llama_firewall.py:98-102` — warning fires inside `_ensure_loaded()` after the component-population loop, guarded by the load path (deferred until package import confirmed). Spec D2 supersedes the brief's `__init__`-time proposal; shipped code follows the spec. |
| D3 | No auto-enable of default components | Confirmed | No auto-enable logic present; empty `self._components` is surfaced as an error, not silently repaired (`llama_firewall.py:172-179`). |
| D4 | Existing test update inverts vulnerable assertion | Confirmed | `tests/test_llama_firewall_scanner.py:202-203` — now asserts `r.error is not None` and `"all components disabled" in r.error`; `r.findings == ()` retained at L201. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `scan()` returns `ScanResult(error=...)` when `self._components` empty after successful load | Met | `petasos/scanners/llama_firewall.py:172-179`. |
| 2 | Constructor logs a warning when all components disabled | Met | Warning emitted (spec D2 relocated it to `_ensure_loaded()`, the authoritative shipped location): `llama_firewall.py:98-102`; verified by `test_all_disabled_warns_on_load` (`tests/test_llama_firewall_scanner.py:223-232`). |
| 3 | `test_no_components_enabled` updated to assert error is returned | Met | `tests/test_llama_firewall_scanner.py:193-204`. |
| 4 | New tests for single-component-enabled paths pass clean | Met | `test_single_component_enabled_no_error` (`tests/test_llama_firewall_scanner.py:216-221`) iterates each flag, asserts `r.error is None`. |
| 5 | `ruff check .` and `mypy --strict .` clean | Unverifiable | Read-only reconciliation; not re-run. Follow-up commit `f998603` removed an unused `type: ignore` specifically to pass `mypy --strict`, indicating the gate was enforced at merge. Test-output artifact present. |
| 6 | No regression in `pytest` full suite | Unverifiable | Not re-run here. `docs/specs/TODO/PET-62.test-output.txt` captures a passing run at ship time. |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| `test_no_components_enabled` (updated) | Yes | `tests/test_llama_firewall_scanner.py:193` |
| `test_no_components_duration_tracked` | Yes | `tests/test_llama_firewall_scanner.py:206` |
| `test_single_component_enabled_no_error` | Yes | `tests/test_llama_firewall_scanner.py:216` |
| `test_all_disabled_warns_on_load` | Yes | `tests/test_llama_firewall_scanner.py:223` |

Note: spec test #4 was named `test_all_disabled_warns_on_load` (shipped) vs. the brief's separate `test_no_components_enabled_no_findings`; the `findings == ()` assertion is folded into the updated `test_no_components_enabled` (L201). Coverage is complete; naming follows the spec, not the brief.

## Wiki-ready
- The warning-emission location was deliberately moved from constructor (brief) to `_ensure_loaded()` (spec D2): constructor-time warning would misleadingly fire when `llamafirewall` is simply not installed, conflating "missing dependency" with "all components disabled." Mildly reusable rationale for any deferred-validation-after-import pattern in the scanner backends.

RECONCILED: yes DRIFT: 0
