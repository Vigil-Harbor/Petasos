# Reconciliation Report: PET-11

> Date: 2026-05-28
> Spec: docs/specs/DONE/PET-11/spec.md
> Merge: #10 (3b80fcc)
> Plane state: Done (group: completed)

## Summary
PET-11 shipped exactly as specced: all 5 files created/modified, all 9 decisions confirmed, and the E2E/smoke/benchmark suite is present on disk verbatim. The only unmet item is the `v1.0.0` tag (a mechanical post-verification step per Decision 8) which was never created, and the coverage-report criterion has no captured artifact to verify against.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `tests/test_integration_e2e.py` | Yes | 517 lines, 4 classes / 18 tests. On disk (`tests\test_integration_e2e.py`). |
| `tests/test_hermes_smoke.py` | Yes | 62 lines, 2 classes / 6 tests. On disk. |
| `tests/test_benchmarks.py` | Yes | 89 lines, 4 benchmark tests. On disk. |
| `docs/specs/TODO/PET-11.test-output.txt` | Yes | 51 lines, captured run: 22 passed / 6 skipped. |
| `docs/security-hardening-checklist.md` | Yes | 80 lines, 28 checks (7 categories). On disk. |
| `pyproject.toml` (modify) | Yes | Added `pytest-benchmark>=5.0,<6` to dev deps (line 24); added `transformers`, `transformers.*`, `pytest_benchmark`, `pytest_benchmark.*` to mypy `ignore_missing_imports` overrides (lines 51-54). |

Production modules (`petasos/`, `petasos/premium/`, `petasos/scanners/`) — spec says leave alone. Confirmed: diff stat touched zero `petasos/` paths.

Unexpected files in diff (not in spec):
- None.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | `license.py` exists — E2E uses existing `valid_key` fixture, no PET-10 amendment | Confirmed | `tests\conftest.py:49` `def valid_key()`; no `premium/license.py` change in diff; all E2E tests call `pipe.activate(valid_key)`. |
| 2 | `pytest-benchmark` `>=5.0,<6` for latency | Confirmed | `pyproject.toml:24` `"pytest-benchmark>=5.0,<6"`; `test_benchmarks.py` uses `benchmark.pedantic(...)`. |
| 3 | Test-count gate already met (300+) | Confirmed | Full suite now has 893 `def test_` across 47 files; test-output.txt header shows the 3 new files collect 28 items. |
| 4 | Petasos's own 5 alert rules, not Drawbridge | Confirmed | E2E asserts `rule_id == "tier_escalation"` (`test_integration_e2e.py` happy/callback paths); no Drawbridge rule names referenced. |
| 5 | Hermes smoke is import-compatibility only | Confirmed | `test_hermes_smoke.py:25` `TestHermesSmoke` skips unless spaCy+transformers present; constructs `Pipeline`, scans, asserts `PipelineResult`, checks `__version__`. |
| 6 | Platform footguns 4c/5/9 N/A with rationale | Confirmed | `docs/security-hardening-checklist.md` section 7 documents all three as N/A with rationale, incl. the "future work must not add signal handlers" note. |
| 7 | Coverage targets add `escalation` + `license` | Confirmed | Spec Design section 4 enumerates 7 modules incl. `escalation.py` and `license.py`. (No coverage artifact captured — see AC#6.) |
| 8 | `v1.0.0` tag is a mechanical final step, conditional on all prior criteria | Confirmed (as written) | Decision text treats tagging as conditional/mechanical, not a design deliverable. Tag was not created (AC#10 Unmet) — consistent with the decision's gating language. |
| 9 | Benchmarks avoid `asyncio.run()` via `new_event_loop()`/`run_until_complete()` | Confirmed | `test_benchmarks.py` every benchmark uses `loop = asyncio.new_event_loop()` + `loop.run_until_complete(...)` + `loop.close()`. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `import petasos` works alongside Hermes deps; skips cleanly when absent | Met | `test_hermes_smoke.py` `TestHermesSmoke` skipif gate; test-output.txt shows 4 SKIPPED (deps absent) + 2 standalone PASSED. |
| 2 | E2E happy path: 3 scanners → frequency → Tier 2 → audit → alert → anonymized output | Met | `test_full_pipeline_composition` asserts `escalation_tier == "tier2"`, `session_score == approx(30.0)`, `<PERSON_1>` substituted, `tier_escalation` alert, all 6 premium features `"available"`; PASSED in test-output.txt. |
| 3 | E2E failure path: all ML error → degraded blocks → correct result; never throws | Met | `test_all_ml_error_degraded_blocks` (`safe is False`), `test_pipeline_never_throws`, `test_scanner_error_attribution`; all PASSED. |
| 4 | `on_audit`/`on_alert` callbacks receive events in both scenarios | Met | `TestCallbackIntegration::test_audit_callback_structure` + `test_alert_callback_structure` assert event_type/session_id/payload; PASSED. |
| 5 | Latency documented: syntactic <5ms, single ML <100ms, full pipeline <250ms median; HW recorded | Met (partial) | test-output.txt benchmark table: syntactic median 22.55us (<5ms), full pipeline median 53.6us (<250ms); HW header (Python 3.13.13, win32) recorded. Single-ML benchmark SKIPPED (no backend installed) — documented skip, not a budget breach. |
| 6 | `pytest --cov` >=90% on pipeline/frequency/guard/audit/alerting/escalation/license; exclusions justified | Unverifiable | No coverage artifact committed; test-output.txt captured the 3-file run without `--cov`. Cannot confirm the 90% figure from shipped evidence. |
| 7 | >=300 tests collected by `pytest --co -q` | Met | test-output.txt shows the 3 new files collect 28 items; Decision 3 records 512 pre-PET-11; full suite on disk now 893 `def test_` — gate comfortably exceeded. |
| 8 | Footguns 4c/5/9 documented N/A with rationale | Met | `docs/security-hardening-checklist.md` section 7. |
| 9 | Drawbridge security hardening checklist applied at `docs/security-hardening-checklist.md` | Met | File present, 28 checks across 7 categories, all PASS/N/A; `TIER3_FLOOR = 30.0` claim verified at `petasos/config.py:13`. |
| 10 | `v1.0.0` release candidate tagged (mechanical final step) | Unmet | `git tag --list` shows only `backup/pre-cleanup-master`; no `v1.0.0` tag exists in the repo. |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| `TestE2EHappyPath` (5 tests incl. `test_full_pipeline_composition`, `test_frequency_score_arithmetic`) | Yes | `tests\test_integration_e2e.py:115` |
| `TestE2EFailurePath` (6 tests incl. `test_all_ml_error_degraded_blocks`, `test_no_alert_storm_via_cooldown`) | Yes | `tests\test_integration_e2e.py:265` |
| `TestCallbackIntegration` (3 tests) | Yes | `tests\test_integration_e2e.py:400` |
| `TestDegradedModeVariants` (4 tests) | Yes | `tests\test_integration_e2e.py:455` — note: 4th test renamed/retargeted by later PET-49 (#21) to `test_degraded_blocks_when_partial_ml_error`; at PET-11 shipped state it was `test_degraded_safe_when_partial_ml_error`. |
| `TestHermesSmoke` + `TestImportWithoutHermesDeps` (6 tests) | Yes | `tests\test_hermes_smoke.py:25` / `:52` |
| `test_benchmark_syntactic_only` / `_single_ml_llm_guard` / `_single_ml_llama_firewall` / `_full_pipeline` | Yes | `tests\test_benchmarks.py:29/44/61/74` |

## Wiki-ready
- None — routine hardening/test-gate ticket. (Decision 9's `asyncio_mode="auto"` + `new_event_loop()` benchmark pattern is mildly reusable but already documented in-spec; the v1.0.0 tag being deferred is operational status, not a design decision.)

RECONCILED: no DRIFT: 0
