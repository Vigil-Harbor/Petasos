# Reconciliation Report: PET-25

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-25.spec.md
> Merge: PR #16 (squash/fix commit c16979c, merged via 056c3f0)
> Plane state: Done (group: completed)

## Summary
PET-25 (strict bool coercion in `PetasosConfig.from_dict` and `__post_init__`) shipped exactly as specified: `_BOOL_FIELDS` frozenset plus `isinstance(val, bool)` enforcement raising `TypeError` on both surfaces, with all 12 tests present on disk. Zero drift.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/config.py` | Yes | `_BOOL_FIELDS` frozenset (config.py:15-28), `__post_init__` guard (112-115), `from_dict` guard (370-372) |
| `tests/test_config.py` | Yes | `TestBoolCoercion` (7 tests, L158) + `TestBoolFieldsCoverage` (1 test, L188) |
| `tests/adversarial/config/test_bool_coercion.py` | Yes | New file, 2 parameterized tests (falsy_int + truthy_non_bool) |
| `tests/adversarial/config/test_config_poisoning.py` | Yes | `test_anonymize_truthy_non_bool_*` updated to expect TypeError (L24) |
| `tests/adversarial/pipeline/test_degraded_fail_open.py` | Yes | `test_from_dict_rejects_normalize_nfkc_falsy_zero` updated to expect TypeError (L385) |
| `petasos/pipeline.py` (leave alone) | No (correct) | Spec said do not touch; absent from diff |
| `petasos/normalize.py` (leave alone) | No (correct) | Spec said do not touch; absent from diff |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-25.test-output.txt` — test-run audit artifact produced by the ship-spec workflow, not a source/spec change. Non-code; not counted as drift.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | `TypeError`, not `ValueError` | Confirmed | config.py:115 and :372 raise `TypeError`; surrounding range checks still use `ValueError` (e.g. :119) |
| 2 | Reject, don't coerce | Confirmed | Guards raise instead of calling `bool()`; config.py:113-115, :371-372 |
| 3 | Both `from_dict` and `__post_init__` | Confirmed | `__post_init__` loop config.py:112-115; `from_dict` loop config.py:370-372 |
| 4 | CFG-02 and CFG-03 are one fix | Confirmed | Same loop covers truthy (1) and falsy (0); adversarial tests cover both (test_bool_coercion.py:11,17) |
| 5 | `_BOOL_FIELDS` frozenset + mechanical coverage test | Confirmed | frozenset config.py:15-28; `test_all_bool_fields_covered` compares `fields()` where `f.type == "bool"` to `_BOOL_FIELDS` (test_config.py:189); verified 10 bool fields all present |
| 6 | Error message simplified to `f"{key} must be a bool, got {val!r}"` | Confirmed | config.py:115 `f"{fname} must be a bool, got {val!r}"`; :372 `f"{key} must be a bool, got {filtered[key]!r}"` — no `type().__name__` prefix |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `_BOOL_FIELDS` frozenset at module scope | Met | config.py:15-28, module level before class |
| 2 | `from_dict` raises `TypeError` for non-bool toggle | Met | config.py:370-372 |
| 3 | `__post_init__` raises `TypeError` for non-bool toggle | Met | config.py:112-115 |
| 4 | All 12 tests pass (7 unit + 1 coverage + 2 adversarial + 2 regressions) | Met | All present: test_config.py:159-189 (8); test_bool_coercion.py:11,17 (2); test_config_poisoning.py:24 (1); test_degraded_fail_open.py:385 (1). PET-25.test-output.txt records the green run |
| 5 | `ruff check .` and `mypy --strict .` clean | Unverifiable | Read-only reconcile; not re-run. No type/lint-suspect constructs introduced |
| 6 | No regression in full `pytest` suite | Unverifiable | Read-only; not re-run. Two prior bypass tests correctly inverted to expect TypeError |
| 7 | PET-52 (PIPE-05) unblocked by this fix | Unverifiable | Downstream ticket state; out of scope for this code reconcile |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| `test_from_dict_rejects_int_zero_for_bool` | Yes | tests/test_config.py:159 |
| `test_from_dict_rejects_int_one_for_bool` | Yes | tests/test_config.py:163 |
| `test_from_dict_rejects_string_for_bool` | Yes | tests/test_config.py:167 |
| `test_from_dict_rejects_none_for_bool` | Yes | tests/test_config.py:171 |
| `test_from_dict_accepts_true_bool` | Yes | tests/test_config.py:175 |
| `test_from_dict_accepts_false_bool` | Yes | tests/test_config.py:179 |
| `test_direct_constructor_rejects_int_for_bool` | Yes | tests/test_config.py:183 |
| `test_all_bool_fields_covered` | Yes | tests/test_config.py:189 |
| `test_from_dict_all_toggles_falsy_int` | Yes | tests/adversarial/config/test_bool_coercion.py:11 |
| `test_from_dict_all_toggles_truthy_non_bool` | Yes | tests/adversarial/config/test_bool_coercion.py:17 |
| `test_anonymize_truthy_non_bool_rejected` | Yes | tests/adversarial/config/test_config_poisoning.py:24 |
| `test_from_dict_rejects_normalize_nfkc_falsy_zero` | Yes | tests/adversarial/pipeline/test_degraded_fail_open.py:385 |

## Wiki-ready
- None — routine hardening fix. The bool/int coercion guard, the reject-don't-coerce stance, and the `_BOOL_FIELDS`+mechanical-coverage pattern are all consistent with the codebase's existing alerting-field `isinstance(..., bool)` guards; nothing novel or constraining beyond the established pattern.

RECONCILED: yes DRIFT: 0
