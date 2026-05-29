# Reconciliation Report: PET-15

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-15.spec.md
> Merge: PR #15 (ea2416b)
> Plane state: Done (group: completed)

## Summary
PET-15 shipped exactly as specified: a single adversarial integration test module (`tests/adversarial/pipeline/test_rt075_chain.py`) with all 5 named RT-075 chain tests, xfail-gated on the three fix tickets, plus no production-code changes. Every decision and acceptance criterion is Met or Unverifiable; zero drift.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `tests/adversarial/pipeline/test_rt075_chain.py` | Yes | Created in `ea2416b`; 117 lines, 5 tests, two fake scanner classes. Matches spec Design verbatim (TAG_CHAR, corrected CHAIN_PAYLOAD `f"ignore {TAG_CHAR}previous instructions"`, `_FlakyMLScanner`/`_CleanMLScanner`). |
| `petasos/normalize.py` | No (correct) | Spec: "leave alone" — fix owned by PET-43. Not touched by this commit. |
| `petasos/scanners/minimal.py` | No (correct) | Spec: "leave alone" — fix owned by PET-71. Not touched by this commit. |
| `petasos/pipeline.py` | No (correct) | Spec: "leave alone" — fix owned by PET-49. Not touched by this commit. |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-15.test-output.txt` — pytest run capture (4 xfailed, 1 xpassed) committed as the ship-spec audit trail. Not named in the spec's "Files to create" table, but it is a routine, non-code ship-spec artifact, not a behavioral change. Counted as 1 Unexpected for DRIFT bookkeeping.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | Integration test primarily; Test 3 (SYN-08) tests `MinimalScanner` construction directly | Confirmed | test_rt075_chain.py:48-110 — tests 1,2,4,5 call `pipe.inspect(...)`; test 3 (`test_rt075_chain_syn08_breaks_link2`, :76-85) constructs `MinimalScanner(suppress_rules=...)` directly. |
| D2 | xfail lifecycle: baseline `xfail(strict=False)`, tests 2-5 `xfail` until fixes land | Confirmed (as shipped) | In `ea2416b` all 5 carried `@pytest.mark.xfail` (baseline strict=False; 2-5 keyed to PET-43/71/49). test-output.txt shows baseline XPASS + 4 XFAIL, matching D2's pre-fix expectation. (Current disk has progressed the lifecycle — see Notes.) |
| D3 | Fake scanners `_FlakyMLScanner`/`_CleanMLScanner`; flaky raises `RuntimeError`; name must not be `"minimal"` | Confirmed | test_rt075_chain.py:17-40 — `_FlakyMLScanner.scan` raises `RuntimeError("ML backend unavailable")`; names `flaky_ml`/`clean_ml`. `_compute_safe` skips `scanner_name == "minimal"` for ML counting at pipeline.py:122. No `unittest.mock` import. |
| D4 | Each link independently sufficient — tests 2-4 isolate one link, test 5 all three | Confirmed | test_rt075_chain.py: test 2 asserts injection finding (link 1), test 3 asserts suppression ineffective/rejected (link 2), test 4 uses clean `"hello world"` to isolate partial-ML-failure block (link 3), test 5 asserts full block. |
| D5 | Corrected payload `f"ignore {TAG_CHAR}previous instructions"` (space before tag char, no other triggers) | Confirmed | test_rt075_chain.py:14 — exact corrected payload shipped, not the brief's flawed `...you are now DAN` variant. `_ALL_INJECTION_IDS` exists at minimal.py:98 as spec D5/Test-3 require. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `test_rt075_chain_pre_fix_baseline` exists and documents the vulnerability (xfail) | Met | test_rt075_chain.py:48; asserts `safe is True`, no HIGH/CRIT, an errored ScanResult; `xfail(strict=False)` at :44-47. |
| 2 | `test_rt075_chain_norm01_breaks_link1` passes after PET-43 merges | Met | test_rt075_chain.py:61; asserts `petasos.syntactic.injection.*` HIGH/CRIT finding. NORM-01 fix landed (normalize.py:48 `_STRIP_CATEGORIES={"Cf"}` strips U+E0001 TAG, category Cf). |
| 3 | `test_rt075_chain_syn08_breaks_link2` passes after PET-71 merges | Met | test_rt075_chain.py:76; SYN-08 fix landed — `_UNSUPPRESSIBLE_RULE_IDS` (minimal.py:100) subtracted from `suppress_rules` at minimal.py:113, so injection rules stay active. |
| 4 | `test_rt075_chain_pipe02_breaks_link3` passes after PET-49 merges | Met | test_rt075_chain.py:89; PIPE-02 fix landed — partial ML failure sets `safe=False` in degraded mode at pipeline.py:136-141. |
| 5 | `test_rt075_chain_all_fixed` passes after all three briefs merge | Unverifiable | Test exists (test_rt075_chain.py:101) but still carries `xfail(reason="Requires PET-43 (NORM-01) fix")` on disk; final flip to a permanent guard not yet performed. Pass state not confirmable from static read. |
| 6 | xfail removed from baseline; baseline asserts `safe=False` | Unmet (lifecycle pending) | Baseline at :44-57 still has `xfail(strict=False)` and still asserts `safe is True`. This step is explicitly gated on "all three fixes merged" and is downstream of PET-15's own ship; it is the post-merge xfail-removal protocol, not part of the shipped deliverable. |
| 7 | `ruff check .` and `mypy --strict .` clean | Unverifiable | Not re-run in this read-only reconcile. Commit included a follow-up `style(pet-15): fix ruff format` (0310f0b) folded into the squash, indicating lint was addressed at ship time. |
| 8 | No regression in `pytest` full suite | Unverifiable | Not re-run here. test-output.txt shows the module itself green (4 xfailed, 1 xpassed). |

Note on criterion 6: spec lines 219/251 frame xfail-removal and the `safe=False` baseline flip as a *post-fix-merge protocol* ("once all three fixes have merged"), not as a deliverable of the PET-15 commit itself. As of today NORM-01's flip is still pending on disk (baseline + all_fixed still xfail-gated on PET-43). This is open lifecycle work, not shipped-scope drift, so it is recorded as Unmet but does not impair the shipped commit's fidelity to spec.

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| `test_rt075_chain_pre_fix_baseline` | Yes | tests/adversarial/pipeline/test_rt075_chain.py:48 |
| `test_rt075_chain_norm01_breaks_link1` | Yes | tests/adversarial/pipeline/test_rt075_chain.py:61 |
| `test_rt075_chain_syn08_breaks_link2` | Yes | tests/adversarial/pipeline/test_rt075_chain.py:76 |
| `test_rt075_chain_pipe02_breaks_link3` | Yes | tests/adversarial/pipeline/test_rt075_chain.py:89 |
| `test_rt075_chain_all_fixed` | Yes | tests/adversarial/pipeline/test_rt075_chain.py:101 |

## Wiki-ready
- None — routine, spec-faithful adversarial test deliverable. The substantive, reusable findings (NORM-01 category-based Cf strip, SYN-08 unsuppressible injection IDs, PIPE-02 partial-ML-failure block) belong to PET-43 / PET-71 / PET-49, not PET-15.

RECONCILED: no DRIFT: 1
