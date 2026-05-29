# Reconciliation Report: PET-49

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-49.spec.md
> Merge: PR #21 (e6f7749)
> Plane state: Done (group: completed)

## Summary
PIPE-02 fix shipped exactly as specified: the one-line `partial_failure` addition to the `degraded` branch of `_compute_safe`, plus config comment, CLAUDE.md invariant update, test rename + 5 new tests, and the RT-075 xfail removal. The diff also touches two pre-existing test files (omitted from the spec's file table but required by the behavioral change) and adds a CI test-output artifact.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/pipeline.py` | Yes | `partial_failure or all_ml_failure` added to degraded branch (current pipeline.py:139-141) |
| `petasos/config.py` | Yes | 3-line tri-state comment above `fail_mode` (current config.py:53-55) |
| `CLAUDE.md` | Yes | Invariant bullet rewritten (current CLAUDE.md:102) |
| `tests/adversarial/pipeline/test_degraded_fail_open.py` | Yes | Renamed test + `_HighFindingScanner` + 5 new tests (lines 30, 50, 61, 72, 83, 94, 105) |
| `tests/adversarial/pipeline/test_rt075_chain.py` | Yes | xfail marker removed from `test_rt075_chain_pipe02_breaks_link3` (current line 89) |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-49.test-output.txt` — new CI/test-output artifact (34 lines); benign, documents the green test run.
- `tests/test_integration_e2e.py` — `test_degraded_safe_when_partial_ml_error` renamed to `test_degraded_blocks_when_partial_ml_error`, assertion flipped to `safe is False` (current line 503). Required by the behavioral change; spec omitted it but commit body documents it as a follow-up fix.
- `tests/test_pipeline.py` — `test_partial_ml_failure_safe_unchanged` renamed to `test_partial_ml_failure_blocks`, assertion flipped to `safe is False` (current line 354). Same rationale.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | `degraded` aligns with `closed` on partial failure | Confirmed | pipeline.py:139-141 degraded uses `partial_failure or all_ml_failure`, identical to closed at pipeline.py:144 |
| D2 | `open` mode unchanged | Confirmed | pipeline.py:142-143 `elif fail_mode == "open": pass`; test_open_partial_ml_failure_passes asserts `safe is True` |
| D3 | No new fail-mode | Confirmed | config.py:56 Literal still `["open", "closed", "degraded"]` |
| D4 | Zero-ML-scanner case unchanged | Confirmed | pipeline.py:133-134 `if ml_total == 0: return safe` (pre-`partial_failure` computation) |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `_compute_safe` treats `partial_failure` as `safe=False` in degraded (one-line change) | Met | pipeline.py:140 `if partial_failure or all_ml_failure:` |
| 2 | `fail_mode` field comment added in config.py | Met | config.py:53-55 three-line tri-state comment |
| 3 | CLAUDE.md invariant updated to reflect partial failure blocks | Met | CLAUDE.md:102 "partial or total ML scanner failure blocks content" |
| 4 | Existing test renamed + assertion flipped | Met | test_degraded_fail_open.py:50 `test_degraded_partial_ml_failure_blocks` asserts `safe is False`; old name absent from source (only stale .pyc) |
| 5 | 6 adversarial tests pass (1 renamed + 5 new) across all three modes | Met | test_degraded_fail_open.py lines 50/61/72/83/94/105; test-output.txt shows all 6 PASSED |
| 6 | `test_rt075_chain_pipe02_breaks_link3` xfail removed, passes | Met | test_rt075_chain.py:88-89 no xfail marker; test-output.txt shows it PASSED |
| 7 | `ruff check .` and `mypy --strict .` clean | Unverifiable | test-output.txt records "All checks passed!" and "Success: no issues found in 55 source files"; not re-run here |
| 8 | No regression in full pytest suite | Unverifiable | Not re-run in this read-only pass; test-output.txt shows 10 passed / 4 xfailed for the targeted files |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| `_HighFindingScanner` mock | Yes | tests/adversarial/pipeline/test_degraded_fail_open.py:30 |
| `test_degraded_partial_ml_failure_blocks` (renamed) | Yes | test_degraded_fail_open.py:50 |
| `test_degraded_all_ml_failure_blocks` | Yes | test_degraded_fail_open.py:61 |
| `test_degraded_no_ml_failure_passes` | Yes | test_degraded_fail_open.py:72 |
| `test_degraded_partial_ml_failure_with_findings_blocks` | Yes | test_degraded_fail_open.py:83 |
| `test_open_partial_ml_failure_passes` | Yes | test_degraded_fail_open.py:94 |
| `test_closed_partial_ml_failure_blocks` | Yes | test_degraded_fail_open.py:105 |
| `test_rt075_chain_pipe02_breaks_link3` (xfail removed) | Yes | tests/adversarial/pipeline/test_rt075_chain.py:89 |
| `test_degraded_blocks_when_partial_ml_error` (e2e, renamed) | Yes | tests/test_integration_e2e.py:503 |
| `test_partial_ml_failure_blocks` (pipeline, renamed) | Yes | tests/test_pipeline.py:354 |

## Wiki-ready
- None — routine hardening fix. The only mildly reusable framing (the precise semantic boundary between `degraded` and `closed` after this change: both block on partial/total ML failure, with `closed` additionally early-exiting on CRITICAL from the syntactic pre-filter) is already captured in config.py:53-55 and the CLAUDE.md invariant.

RECONCILED: yes DRIFT: 3
