# PET-23 Spec: Config Immutability Hardening

**Covers:** PET-23 (CFG-01), PET-26 (CFG-04), PET-27 (CFG-05)
**Parent:** PET-14 (red-team security review)

## Goal

Harden `PetasosConfig` against post-construction mutation attacks discovered during PET-14 red-teaming. Three findings: `object.__setattr__` bypasses frozen dataclass (CFG-01), mutable module-level `TIER3_FLOOR` constant (CFG-04), and pipeline's config copy inheriting the same vulnerability (CFG-05). The fix uses `slots=True` to eliminate `__dict__`, adds `typing.Final` annotation to `TIER3_FLOOR`, and inserts runtime validation guards at critical consumption points.

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/config.py` | Add `slots=True` to `PetasosConfig`, annotate `TIER3_FLOOR` as `Final[float]` |
| `petasos/premium/escalation.py` | Add runtime floor guard in `evaluate_tier()` — fail-secure return, not raise |
| `petasos/pipeline.py` | Replace `config.copy()` with `dataclasses.replace(config)`, validate `fail_mode` at `_compute_safe()` entry |
| `tests/adversarial/config/test_config_poisoning.py` | Flip CFG-01 test, add new tests for CFG-04 runtime guard and CFG-05 pipeline isolation |

**Scope expansion note:** The brief's "Files touched" lists only `config.py` and `tests/adversarial/config/`. The spec expands to `escalation.py` and `pipeline.py` because the brief's own "Approach" section calls for "runtime assertion in `evaluate_tier()`" (CFG-04) and "`copy.deepcopy` at Pipeline construction" (CFG-05). The runtime guards ARE the fix for the residual `object.__setattr__` bypass that `slots=True` cannot prevent.

### Files to leave alone

- `petasos/_types.py` -- types hardening is Brief 2 (PET-72/73/74)
- `petasos/premium/guard.py` -- guard uses `_derive_tier()` which calls `evaluate_tier()`; the new guard propagates through existing call chain
- `tests/test_config.py` -- existing functional tests; verify they still pass but don't modify

## Decisions

### D1: `slots=True` behavior (CFG-01)

**Finding:** The brief claims `slots=True` makes `object.__setattr__` fail with `AttributeError`. **This is incorrect.** Empirically verified: `object.__setattr__` on a `frozen=True, slots=True` dataclass still successfully sets slot values. `PyObject_GenericSetAttr` finds the slot's `member_descriptor` and calls its `__set__` method, bypassing the class-level `__setattr__` override.

**What `slots=True` actually prevents:**
1. Dict-based mutation: `cfg.__dict__["fail_mode"] = "open"` -- no `__dict__` exists
2. New attribute injection: `cfg.evil = True` -- no `__dict__` to store it
3. Attribute enumeration attacks via `__dict__`

**What it does NOT prevent:**
- `object.__setattr__(cfg, "fail_mode", "open")` on defined fields -- still works

**Decision:** Add `slots=True` anyway -- it closes the `__dict__` vector and prevents new-attribute injection, which is genuine defense in depth. For the residual `object.__setattr__` bypass, add **runtime validation at critical consumption points** (D3, D4). This is the standard Python approach: you can't prevent `object.__setattr__` in pure Python, so you validate invariants where they matter.

**Impact on existing code:** `PetasosConfig.__post_init__` uses `object.__setattr__` in two places to coerce `pii_entities` to tuple and `frequency_weights` to `MappingProxyType`. These calls still work with `slots=True` because they operate on defined slots. No changes needed.

**Brief criterion revision:** Brief "Done when" criterion 1 says `object.__setattr__(config, "fail_mode", "open")` raises `AttributeError`. This is unachievable with `slots=True` (or any pure-Python mechanism). Replacement criteria: no `__dict__`, no new attribute injection, runtime guards at consumption points.

### D2: `TIER3_FLOOR` hardening (CFG-04)

Add `typing.Final` annotation -- static analysis hint only, but catches accidental reassignment in typed code.

The real defense is a runtime guard in `evaluate_tier()` that validates `config.tier3_threshold >= 30.0` using the **inline literal `30.0`** directly in the comparison. No intermediate variable -- an attacker who can mutate a module-level variable cannot mutate a literal embedded in compiled bytecode.

**Re-export chain:** `TIER3_FLOOR` is re-exported via `petasos.premium.escalation` (line 9) and `petasos.premium.__init__`. Mutating either re-export has no effect on the runtime guard because the guard uses the inline literal, not any module-level binding.

### D3: Pipeline config isolation (CFG-05)

Replace `config.copy()` (which uses `from_dict(to_dict())`) with `dataclasses.replace(config)`.

**Why `dataclasses.replace` instead of `copy.deepcopy`:** `PetasosConfig.__post_init__` wraps `frequency_weights` in `MappingProxyType`. `copy.deepcopy()` raises `TypeError: cannot pickle 'mappingproxy' object` on any config with non-None `frequency_weights`. `dataclasses.replace()` avoids this: it creates a new instance via `__init__`, which calls `__post_init__`, re-applying the `MappingProxyType` wrapping. It also preserves `session_secret` (which `to_dict()` strips), eliminating the `object.__setattr__` workaround in `Pipeline.__init__`.

Additionally, add a `fail_mode` validation guard in `_compute_safe()` with logging -- if `fail_mode` is not one of the three expected values (indicating post-construction tampering), log a warning and treat as `"degraded"` (fail-secure default).

### D4: Runtime validation strategy

**`evaluate_tier()` fail-secure, not raise:** The runtime guard in `evaluate_tier()` returns `"tier3"` (the most restrictive tier) instead of raising `ValueError` when `config.tier3_threshold < 30.0`. Rationale:
1. **Frequency tracker state integrity.** `FrequencyTracker.update()` modifies the rolling window before calling `evaluate_tier()`. A `ValueError` would leave the session with an updated rolling window but no score, corrupting state.
2. **Pipeline never throws.** Although the pipeline catches `Exception` in the escalation hook, a raised `ValueError` causes the escalation result to be silently lost (fail-open). Returning `"tier3"` is fail-secure -- a tampered tier3 threshold triggers the most restrictive response.
3. **Guard propagation.** `ToolCallGuard.evaluate()` does not catch exceptions from `_derive_tier()`. A `ValueError` would propagate unhandled. Returning `"tier3"` produces a safe guard result instead.

## Design

### 1. `PetasosConfig` slots (CFG-01)

```python
@dataclass(frozen=True, slots=True)
class PetasosConfig:
    ...
```

Single-line change. The `__post_init__` `object.__setattr__` calls continue to work on defined slots.

### 2. `TIER3_FLOOR` annotation (CFG-04)

```python
from typing import Final

TIER3_FLOOR: Final[float] = 30.0
```

### 3. Runtime guard in `evaluate_tier()` (CFG-04)

In `petasos/premium/escalation.py`, add a runtime floor check at the top of `evaluate_tier()` that returns fail-secure with logging:

```python
import logging

_logger = logging.getLogger(__name__)

def evaluate_tier(score: float, config: PetasosConfig) -> str:
    if config.tier3_threshold < 30.0:
        _logger.warning(
            "tier3_threshold %r < 30.0 floor; returning tier3 fail-secure",
            config.tier3_threshold,
        )
        return "tier3"
    ...
```

The literal `30.0` cannot be influenced by module-level mutation. A tampered threshold triggers the most restrictive tier with a warning log, which is fail-secure and observable.

### 4. Pipeline config via `dataclasses.replace` (CFG-05)

In `Pipeline.__init__`:

```python
from dataclasses import replace

self._config = replace(config) if config is not None else PetasosConfig()
```

Remove the `object.__setattr__` workaround for `session_secret` -- `replace()` preserves all fields including `session_secret`.

### 5. `_compute_safe()` fail_mode guard (CFG-05 defense-in-depth)

Add a validation check with logging in `_compute_safe()`:

```python
import logging

_logger = logging.getLogger(__name__)

def _compute_safe(
    findings: tuple[ScanFinding, ...],
    scanner_results: Sequence[ScanResult],
    fail_mode: str,
) -> bool:
    if fail_mode not in ("open", "closed", "degraded"):
        _logger.warning("fail_mode %r is invalid, falling back to 'degraded'", fail_mode)
        fail_mode = "degraded"
    ...
```

This catches post-construction `fail_mode` tampering by falling back to `"degraded"` and logging the anomaly.

## Test plan

All tests in `tests/adversarial/config/test_config_poisoning.py`.

### Existing test changes

1. **Flip `test_frozen_config_bypass_via_setattr`** -- currently asserts the bypass works. Update to assert `AttributeError` on `__dict__` access (the `slots=True` vector it actually prevents). Keep the `object.__setattr__` call to document the residual.

2. **Flip `test_tier3_floor_module_global_mutable`** -- currently asserts `TIER3_FLOOR` mutation succeeds and `tier3_threshold=10.0` is accepted. After CFG-04 fix, the config construction still succeeds (because `__post_init__` reads the mutated `TIER3_FLOOR`), but `evaluate_tier()` returns `"tier3"` fail-secure.

### New tests

3. **`test_slots_no_dict`** -- `PetasosConfig()` has no `__dict__` attribute: `not hasattr(cfg, '__dict__')`.

4. **`test_slots_no_new_attr`** -- `object.__setattr__(cfg, "evil", True)` raises `AttributeError`.

5. **`test_object_setattr_on_defined_field_residual`** -- documents that `object.__setattr__` on defined fields still works (accepted residual, Python limitation).

6. **`test_evaluate_tier_failsecure_on_low_tier3`** -- Tamper `config.tier3_threshold` below 30.0 via `object.__setattr__`, call `evaluate_tier()` -- returns `"tier3"` (fail-secure).

7. **`test_evaluate_tier_ignores_module_mutation`** -- Use `monkeypatch.setattr(config_mod, "TIER3_FLOOR", 5.0)` (auto-restored by pytest), construct a config with `tier3_threshold=10.0`, call `evaluate_tier()` -- returns `"tier3"` (the inline `30.0` check catches it).

8. **`test_pipeline_config_isolation`** -- Construct `Pipeline(config=cfg)`, then `object.__setattr__(cfg, "fail_mode", "open")` on the original. Pipeline's internal config is unchanged (`pipeline.config.fail_mode == "degraded"`).

9. **`test_pipeline_replace_preserves_session_secret`** -- Construct pipeline with `session_secret=b"key"` and `host_id="h1"`. Verify `pipeline.config.session_secret == b"key"`.

10. **`test_compute_safe_fallback_on_invalid_fail_mode`** -- `_compute_safe((), [ScanResult(scanner_name="ml1", findings=(), duration_ms=0, error="fail")], "evil")` falls back to `"degraded"` behavior -- returns `safe=False` because degraded mode treats ML scanner errors as unsafe. Must include an errored ML scanner to exercise the fail_mode branching logic (empty scanner list hits early return before fail_mode is checked).

## Test command

```
python -m pytest tests/adversarial/config/test_config_poisoning.py tests/test_config.py tests/test_pipeline.py tests/test_escalation.py -x -v && ruff check petasos/config.py petasos/premium/escalation.py petasos/pipeline.py && ruff format --check petasos/config.py petasos/premium/escalation.py petasos/pipeline.py && python -m mypy --strict petasos/config.py petasos/premium/escalation.py petasos/pipeline.py
```

## Done when

**NOTE:** Brief criterion 1 (`object.__setattr__` raises `AttributeError`) is revised per D1/D4 -- `slots=True` does not prevent `object.__setattr__` on defined fields (empirically verified). Replacement criteria below.

- [ ] `PetasosConfig` uses `slots=True` -- `hasattr(cfg, '__dict__')` is `False`
- [ ] `object.__setattr__` on new attributes raises `AttributeError` (no `__dict__`)
- [ ] `TIER3_FLOOR` annotated as `Final[float]`
- [ ] `evaluate_tier()` returns `"tier3"` fail-secure when `tier3_threshold < 30.0` (inline literal, not mutable variable)
- [ ] Pipeline stores config via `dataclasses.replace()` -- mutating the original after construction has no effect
- [ ] Pipeline's `session_secret` is preserved without the `object.__setattr__` workaround
- [ ] `_compute_safe()` logs warning and falls back to `"degraded"` on invalid `fail_mode` values
- [ ] >= 10 tests covering all three findings
- [ ] `mypy --strict` clean on changed files
- [ ] No breakage in existing config, pipeline, and escalation tests

## Out of scope

- Making all dataclasses across the codebase `slots=True` (follow-up sweep)
- Hardware-level memory protection (out of Python's reach)
- Preventing `object.__setattr__` on defined slot fields (Python language limitation -- accepted residual, documented in test)
- Full config integrity hashing at every `inspect()` call (over-engineering for the threat model -- `object.__setattr__` requires code execution)
- Fixing `PetasosConfig.copy()` method to preserve `session_secret` (existing pre-existing issue; Pipeline now uses `dataclasses.replace()` which does preserve it; `copy()` method fix is a follow-up)
- `TIER3_FLOOR` re-export chain mutation (runtime guard uses inline literal `30.0`, making re-export mutation irrelevant)

## Deferred (P2+)

- conventions/R1/F-2: `_HARDCODED_TIER3_FLOOR` naming -- resolved: using inline literal `30.0` instead of a named variable, making the naming question moot.
- edge-cases/R1/F-4: Test 11 (`Final` annotation runtime check) -- dropped. `typing.Final` is a static analysis hint; runtime introspection via `get_type_hints` is version-dependent and brittle. `mypy --strict` in the test command validates the annotation statically.
- conventions/R1/F-8: Novel `get_type_hints` test pattern -- resolved by dropping Test 11.
- edge-cases/R2/F-3: `_validate_tier_thresholds` still reads mutable `TIER3_FLOOR` at construction time. Accepted: runtime guard in `evaluate_tier()` is the true enforcement point; construction-time validation is defense-in-depth that reads the mutable variable by design (see D2).
- edge-cases/R2/F-4: `dataclasses.replace()` is shallow -- relies on `__post_init__` wrapping all mutable fields immutable. Future mutable fields must be similarly wrapped.
- conventions/R2/F-6: Brief's `copy.deepcopy` instruction superseded by `dataclasses.replace()` -- D3 provides full rationale for the substitution.
