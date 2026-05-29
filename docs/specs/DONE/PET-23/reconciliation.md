# Reconciliation Report: PET-23

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-23.spec.md
> Merge: #43 (dfa7eef)
> Plane state: Done (group: completed)

## Summary
CFG-01 (slots) and CFG-05 (pipeline isolation, fail_mode fallback) shipped as
specified. CFG-04 drifted: the spec's D2/D4 explicitly mandate an **inline
literal `30.0`** in the `evaluate_tier()` guard so that module-level /
re-export mutation of `TIER3_FLOOR` is irrelevant; the shipped guard instead
compares against the mutable imported `TIER3_FLOOR` binding, which the spec's
own "Out of scope" line claims is made irrelevant.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/config.py` | Yes | `slots=True` added (`config.py:43`); `TIER3_FLOOR: Final[float]` (`config.py:13`). |
| `petasos/premium/escalation.py` | Yes | Runtime floor guard added in `evaluate_tier()` (`escalation.py:42-48`), fail-secure return. Uses `TIER3_FLOOR` variable, not inline literal (see Decisions D2/D4). |
| `petasos/pipeline.py` | Yes | `replace(config)` replaces `config.copy()` + `object.__setattr__` workaround (`pipeline.py:199`); `_compute_safe()` fail_mode guard (`pipeline.py:109-111`). |
| `tests/adversarial/config/test_config_poisoning.py` | Yes | CFG-01 test flipped, 9 new tests added (12 total functions). |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-23.test-output.txt` — captured test output (audit artifact from ship-spec; non-code, benign).

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | `slots=True` closes `__dict__` vector + new-attr injection; `object.__setattr__` on defined fields accepted residual | Confirmed | `config.py:43` `@dataclass(frozen=True, slots=True)`; `__post_init__` `object.__setattr__` on defined slots still works; tests `test_slots_no_dict`, `test_slots_no_new_attr`, `test_object_setattr_on_defined_field_residual` (test file lines 50, 56, 63). |
| D2 | `TIER3_FLOOR` → `Final`; real defense is runtime guard using **inline literal `30.0`** so re-export mutation is irrelevant | Drifted | `config.py:13` has `Final[float]` (confirmed), but `escalation.py:43` reads `config.tier3_threshold < TIER3_FLOOR` — the module-level imported binding (`escalation.py:11` `from petasos.config import TIER3_FLOOR`), NOT an inline `30.0`. Reassigning `escalation.TIER3_FLOOR` (or the `petasos.premium.__init__` re-export at `__init__.py:5`) directly changes the guard's comparand, defeating the protection the spec claimed was "irrelevant" to re-export mutation. |
| D3 | Pipeline isolation via `dataclasses.replace(config)`; preserves `session_secret`; remove `object.__setattr__` workaround | Confirmed | `pipeline.py:8` `from dataclasses import replace`; `pipeline.py:199` `self._config = replace(config) if config is not None else PetasosConfig()`; old `object.__setattr__` session_secret workaround removed (diff). `_compute_safe()` fail_mode fallback at `pipeline.py:109-111`. |
| D4 | `evaluate_tier()` returns `"tier3"` fail-secure (not raise) when `tier3_threshold < 30.0`, using inline literal | Drifted | Fail-secure return confirmed (`escalation.py:48` `return "tier3"`, no raise). But the comparison uses module variable `TIER3_FLOOR` not inline `30.0` (`escalation.py:43`) — same drift as D2. Shipped code also ADDED a `math.isfinite()` non-finite check (`escalation.py:43`) not in the spec's code sample — a defensible improvement, but the literal-vs-variable mechanism diverged. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `slots=True` — `hasattr(cfg,'__dict__')` is False | Met | `config.py:43`; `test_slots_no_dict` (line 50). |
| 2 | `object.__setattr__` on new attrs raises `AttributeError` | Met | `test_slots_no_new_attr` (line 56). |
| 3 | `TIER3_FLOOR` annotated `Final[float]` | Met | `config.py:13`. |
| 4 | `evaluate_tier()` returns `"tier3"` fail-secure when `tier3_threshold < 30.0` (inline literal, not mutable variable) | Met (behavior) / Unmet (mechanism) | Fail-secure behavior present (`escalation.py:42-48`), but criterion explicitly says "inline literal, not mutable variable" — shipped code uses the mutable imported `TIER3_FLOOR` variable (`escalation.py:43`), violating the parenthetical requirement. Counted as Unmet (mechanism specified, not delivered). |
| 5 | Pipeline stores config via `dataclasses.replace()`; mutating original has no effect | Met | `pipeline.py:199`; `test_pipeline_config_isolation` (line 87). |
| 6 | `session_secret` preserved without `object.__setattr__` workaround | Met | workaround removed (diff); `test_pipeline_replace_preserves_session_secret` (line 96). |
| 7 | `_compute_safe()` logs warning + falls back to `"degraded"` on invalid `fail_mode` | Met | `pipeline.py:109-111`; `test_compute_safe_fallback_on_invalid_fail_mode` (line 104). |
| 8 | >= 10 tests covering all three findings | Met | 12 test functions in `test_config_poisoning.py` (lines 14-104). |
| 9 | `mypy --strict` clean on changed files | Unverifiable | mypy not re-run (read-only reconcile, Bash classifier intermittently unavailable); `PET-23.test-output.txt` artifact present as ship-time evidence. |
| 10 | No breakage in existing config/pipeline/escalation tests | Unverifiable | Test suite not re-run here; ship-time test-output artifact present. |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| `test_frozen_config_bypass_via_setattr` (flipped) | Yes | test_config_poisoning.py:14 |
| `test_tier3_floor_module_global_mutable` (flipped, monkeypatch) | Yes | test_config_poisoning.py:30 |
| `test_slots_no_dict` | Yes | test_config_poisoning.py:50 |
| `test_slots_no_new_attr` | Yes | test_config_poisoning.py:56 |
| `test_object_setattr_on_defined_field_residual` | Yes | test_config_poisoning.py:63 |
| `test_evaluate_tier_failsecure_on_low_tier3` | Yes | test_config_poisoning.py:71 |
| `test_evaluate_tier_ignores_module_mutation` | Yes (but weak) | test_config_poisoning.py:79 — patches `config_mod.TIER3_FLOOR`, a different binding than the `escalation.TIER3_FLOOR` the guard reads; passes without exercising the claimed protection. |
| `test_pipeline_config_isolation` | Yes | test_config_poisoning.py:87 |
| `test_pipeline_replace_preserves_session_secret` | Yes | test_config_poisoning.py:96 |
| `test_compute_safe_fallback_on_invalid_fail_mode` | Yes | test_config_poisoning.py:104 |

## Wiki-ready
- **`evaluate_tier()` floor guard reads the module-level `TIER3_FLOOR` import, not an inline `30.0` literal.** This contradicts the spec's stated CFG-04 threat model (D2/D4: re-export/module mutation should be irrelevant). As shipped, reassigning `petasos.premium.escalation.TIER3_FLOOR` or the `petasos.premium` re-export defeats the runtime guard. Constraining/non-obvious because the spec's "Out of scope" line asserts the opposite is true. Either the code should switch to a literal `30.0`, or the spec/threat-model note should be corrected to reflect that the guard is mutable-binding-based and the test re-pointed at `escalation.TIER3_FLOOR`.

RECONCILED: no DRIFT: 3
