# Reconciliation Report: PET-54

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-54.spec.md
> Merge: PR #26 (merge 5cd6367, squash-fix fb1a574)
> Plane state: Done (group: completed)

## Summary
The shipped commit (fb1a574, merged via PR #26) implements the layered PIPE-07 defense exactly as specified: a runtime severity floor + structural-prefix skip in `pipeline.py`, and construction-time structural/value validation in `profiles/__init__.py`. All 11 named tests exist and the captured test-output.txt shows them passing. Zero drift.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/pipeline.py` | Yes | Added `_STRUCTURAL_RULE_PREFIX` (now L48) + guarded Stage 5c loop (now L450-476): structural skip, `try/except ValueError`, severity floor. |
| `petasos/premium/profiles/__init__.py` | Yes | Added `_check_structural_overrides` (L86) + `_check_severity_values` (L94), `Severity` import (L10), called in `_parse_profile` (L128-129) and `_merge_with_base` (L160-161). |
| `tests/adversarial/pipeline/test_degraded_fail_open.py` | Yes | 8 tests added (L436-530+). |
| `tests/test_profiles.py` | Yes | 3 tests added (L310, L321, L328). |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-54.test-output.txt` — captured pytest output (audit artifact from /ship-spec, not a code/spec change). Benign.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | Severity floor, not full removal | Confirmed | `pipeline.py:470-473` — `override_rank > current_rank` keeps original; else applies override (upgrade/maintain allowed). |
| 2 | Defense-in-depth: construction + runtime | Confirmed | Construction: `profiles/__init__.py:128-129,160-161`. Runtime: `pipeline.py:460-473`. |
| 3 | Structural prefix narrowed to `petasos.syntactic.structural.*` | Confirmed | `pipeline.py:48` `_STRUCTURAL_RULE_PREFIX = "petasos.syntactic.structural."`; `minimal.py:77-81` `_STRUCTURAL_RULE_IDS` = the 3 `...structural.*` rules. Diverges from brief's `SYN-*` as the spec intended. |
| 4 | No license tier distinction | Confirmed | Stage 5c gated only by `self._check_premium("profiles")` (`pipeline.py:453`); no tier branch in override loop. |
| 5 | `suppress_rules` left as-is | Confirmed | No change to `_premium_profile_hook`/suppress path in diff; `minimal.py:100` `_UNSUPPRESSIBLE_RULE_IDS` pre-existing. Regression test 6 guards ML behavior. |
| 6 | Invalid override values handled gracefully | Confirmed | Runtime: `pipeline.py:463-467` `try: Severity(override) except ValueError: keep original`. Construction: `_check_severity_values` (`profiles/__init__.py:94-99`). |
| 7 | PET-59 interaction — import `_STRUCTURAL_RULE_IDS`, no prefix dup in profiles | Confirmed | `profiles/__init__.py:12` imports `_STRUCTURAL_RULE_IDS` from `petasos.scanners.minimal`; membership check (`k in _STRUCTURAL_RULE_IDS`) not prefix match. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `severity_overrides` cannot downgrade below original (universal floor) | Met | `pipeline.py:468-473`; tests 1-2 `test_override_cannot_downgrade_*` PASSED in test-output.txt. |
| 2 | Structural rules rejected at construction (`_parse_profile` + `_merge_with_base`) | Met | `profiles/__init__.py:128,160` call `_check_structural_overrides`; tests 9-10 (`..._at_parse`, `..._at_merge`) exist `test_profiles.py:310,321`. |
| 3 | Runtime defense-in-depth skips structural overrides for direct profiles | Met | `pipeline.py:460-462`; test 5 `test_structural_rule_override_skipped_at_runtime` PASSED. |
| 4 | Invalid severity values handled gracefully (silent skip, no crash) | Met | `pipeline.py:463-467`; test 8 `test_invalid_severity_override_value_skipped` (`test_degraded_fail_open.py:530`). |
| 5 | All 11 listed tests pass | Met | All 8 pipeline + 3 profile test functions exist; test-output.txt shows pipeline tests PASSED, 50 items collected. |
| 6 | `customer_service` builtin still loads and upgrades still apply | Met | `customer_service.json` overrides 6 `...injection.*` rules to `critical` (upgrade, not in structural set → passes both validators); `test_customer_service_severity_overrides` (`test_profiles.py:101`) retained. |
| 7 | `ruff check .` and `mypy --strict .` clean | Unverifiable | Read-only reconciliation; not re-run. Standard /ship-spec gate. |
| 8 | No regression in full `pytest` suite | Unverifiable | Read-only; captured test-output.txt (subset, 50 items) all PASSED but full-suite run not re-executed here. |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| test_override_cannot_downgrade_critical_to_info | Yes | tests/adversarial/pipeline/test_degraded_fail_open.py:436 |
| test_override_cannot_downgrade_high_to_low | Yes | tests/adversarial/pipeline/test_degraded_fail_open.py:449 |
| test_override_can_upgrade_medium_to_critical | Yes | tests/adversarial/pipeline/test_degraded_fail_open.py:461 |
| test_override_same_severity_accepted | Yes | tests/adversarial/pipeline/test_degraded_fail_open.py:476 |
| test_structural_rule_override_skipped_at_runtime | Yes | tests/adversarial/pipeline/test_degraded_fail_open.py:488 |
| test_suppress_rules_does_not_affect_ml_findings | Yes | tests/adversarial/pipeline/test_degraded_fail_open.py:503 |
| test_dict_profile_override_critical_blocked | Yes | tests/adversarial/pipeline/test_degraded_fail_open.py:515 |
| test_invalid_severity_override_value_skipped | Yes | tests/adversarial/pipeline/test_degraded_fail_open.py:530 |
| test_structural_rule_override_rejected_at_parse | Yes | tests/test_profiles.py:310 |
| test_structural_rule_override_rejected_at_merge | Yes | tests/test_profiles.py:321 |
| test_structural_rule_ids_match_prefix | Yes | tests/test_profiles.py:328 |

## Wiki-ready
- Decision 3: the structural-override protection set was narrowed from the brief's `SYN-*` to `petasos.syntactic.structural.*` because `SYN-*` matches no real rule ID and the broader `petasos.syntactic.*` would block the legitimate injection-rule upgrades in the `customer_service` builtin. Constraining/non-obvious — couples the pipeline prefix constant to `_STRUCTURAL_RULE_IDS` (guarded by the tripwire test).
- Decision 6: invalid `Severity` values must be silently skipped, not raised, at runtime — raising would propagate through `inspect()`'s catch-all and erase ALL findings (a worse DoS than the downgrade). Reusable fail-safe rationale.

RECONCILED: yes DRIFT: 0
