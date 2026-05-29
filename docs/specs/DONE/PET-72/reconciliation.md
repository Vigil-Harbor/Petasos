# Reconciliation Report: PET-72

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-72.spec.md
> Merge: PR #36 (0c38d74)
> Plane state: Done (group: completed)

## Summary
The shipped commit (squash-merge PR #36, `0c38d74`) implements all four PET-72 decisions exactly as specified: `Position`/`ScanFinding`/`PipelineResult` construction-time validation and `_validate_scanner()` at `Pipeline.__init__`. All eight acceptance criteria are met with 18 adversarial tests present; zero drift in source/test scope.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/_types.py` | Yes | `import inspect`, `MappingProxyType` promoted from `TYPE_CHECKING`, `TYPE_CHECKING` removed from typing import, three `__post_init__` methods, `_validate_scanner()` added (`_types.py:1-7,25-29,43-47,120-158,205-208`) |
| `petasos/pipeline.py` | Yes | `_validate_scanner` imported (`pipeline.py:20`) and called per scanner in `__init__` (`pipeline.py:208-209`) |
| `tests/adversarial/types/test_type_validation.py` (create) | Yes | 18 tests across 5 test classes; no `__init__.py` added (matches convention per spec) |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-72.test-output.txt` — ship-spec test-audit artifact, not a code/spec change. Routine and harmless; counts toward drift per the mechanical rule.

Files correctly left alone (spec §"Files to leave alone"): `petasos/__init__.py`, `petasos/config.py`, `petasos/scanners/*`, `petasos/premium/*`, `tests/test_types.py` — none appear in the diff. (Note: the BRIEF listed `tests/test_types.py` as touched; the SPEC overrode this to "leave alone," and the diff honors the spec.)

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | TYP-02 scoped to `PipelineResult.premium_features` only; shallow `MappingProxyType(dict(...))` wrap, defense-in-depth | Confirmed | `_types.py:205-208` wraps only `premium_features`; `ScanFinding`/`AuditEvent`/`Alert` have no added `__post_init__` for maps (`_types.py:171-189` unchanged) |
| 2 | Confidence raises (not clamps); NaN/inf rejected | Confirmed | `_types.py:43-47` raises `ValueError` for `not (0.0 <= confidence <= 1.0)`; tests `test_confidence_nan_raises`, `test_confidence_inf_raises` (test file:93-99) |
| 3 | `_validate_scanner()` private, signature-at-registration check, `**kwargs` bypass | Confirmed | `_types.py:120-158`; checks `name`, async `scan`, signature params. Post-merge refinement (commit cfa7179): `text` now required independently of `**kwargs` (`_types.py:150-151`) — strengthens, does not contradict, the decision (only `direction`/`session_id` keyword checks are `**kwargs`-bypassed, `_types.py:153-158`) |
| 4 | Negative start rejected (spec addition); zero-length valid | Confirmed | `_types.py:25-29` rejects `start < 0` and `end < start`; `test_position_zero_length_accepted` accepts `Position(5,5)` (test file:78-81) |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Mutating `premium_features` dict on constructed `PipelineResult` raises `TypeError` | Met | `_types.py:205-208` wraps to `MappingProxyType`; `test_pipeline_result_proxy_mutation_raises` (test file:44-52) |
| 2 | `Position(start=10, end=5)` raises `ValueError` | Met | `_types.py:28-29`; `test_position_inverted_raises` (test file:70-72) |
| 3 | `ScanFinding(confidence=1.5)` raises `ValueError` | Met | `_types.py:44-47`; `test_confidence_above_one_raises` (test file:85-87) |
| 4 | Non-conforming scanner to `Pipeline()` raises `TypeError` | Met | `pipeline.py:208-209` calls `_validate_scanner`; `test_pipeline_rejects_invalid_scanner` (test file:175-180) |
| 5 | `from_dict` round-trip preserves immutability/validation | Met | `test_from_dict_roundtrip_preserves_validation` (test file:188-202) exercises confidence + position validation through `from_dict` |
| 6 | >= 18 tests pass (4 TYP-02 + 7 TYP-03 + 6 TYP-04 + 1 cross-cutting) | Met | 18 tests in file: 4 immutability + 3 position + 4 confidence + 6 scanner + 1 roundtrip. (Confidence has 4 not the spec-table's wording; total 18.) `PET-72.test-output.txt` shows 18 passed |
| 7 | `mypy --strict` clean | Unverifiable | Not re-run here (read-only reconcile); `PET-72.test-output.txt` is the shipped audit trail of the test command which includes mypy |
| 8 | No regression in existing types/pipeline tests | Met | `tests/test_types.py` unchanged in diff; new tests are additive under `tests/adversarial/types/` |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| test_pipeline_result_dict_wrapped_as_proxy | Yes | test_type_validation.py:36 |
| test_pipeline_result_proxy_mutation_raises | Yes | test_type_validation.py:44 |
| test_pipeline_result_none_stays_none | Yes | test_type_validation.py:54 |
| test_pipeline_result_proxy_not_double_wrapped | Yes | test_type_validation.py:58 |
| test_position_inverted_raises | Yes | test_type_validation.py:70 |
| test_position_negative_start_raises | Yes | test_type_validation.py:74 |
| test_position_zero_length_accepted | Yes | test_type_validation.py:78 |
| test_confidence_above_one_raises | Yes | test_type_validation.py:85 |
| test_confidence_below_zero_raises | Yes | test_type_validation.py:89 |
| test_confidence_nan_raises | Yes | test_type_validation.py:93 |
| test_confidence_inf_raises | Yes | test_type_validation.py:97 |
| test_validate_scanner_accepts_valid | Yes | test_type_validation.py:108 |
| test_validate_scanner_missing_name | Yes | test_type_validation.py:111 |
| test_validate_scanner_missing_scan | Yes | test_type_validation.py:125 |
| test_validate_scanner_sync_scan_rejected | Yes | test_type_validation.py:134 |
| test_validate_scanner_accepts_kwargs_scan | Yes | test_type_validation.py:152 |
| test_validate_scanner_rejects_scan_without_text (post-merge regression) | Yes | test_type_validation.py:163 |
| test_from_dict_roundtrip_preserves_validation | Yes | test_type_validation.py:189 |

Note: the spec test table named test #17 `test_pipeline_rejects_invalid_scanner` separately; the shipped file contains it (test file:175) plus the added `test_validate_scanner_rejects_scan_without_text` — still 18 distinct tests (one TYP-04 slot consolidated, regression test added).

## Wiki-ready
- None — routine hardening fix. The one mildly reusable nuance (`_validate_scanner` checks `text`/`*args` independently of `**kwargs`, while only `direction`/`session_id` are `**kwargs`-bypassed) is a local validation refinement, not a constraining architecture decision.

RECONCILED: yes DRIFT: 1
