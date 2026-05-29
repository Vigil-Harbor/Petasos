# Brief 3 -- Config Immutability

**Plane items:** PET-23 (CFG-01), PET-26 (CFG-04), PET-27 (CFG-05)
**Files touched:** `petasos/config.py`, `tests/adversarial/config/`
**Priority:** medium (CFG-01, CFG-04 confirmed); low (CFG-05 confirmed)

## Findings

| ID | Severity | Attack | Current behavior | Remediation |
|----|----------|--------|------------------|-------------|
| CFG-01 | medium | `object.__setattr__(config, "fail_mode", "open")` | Frozen dataclass bypassed via `object.__setattr__` -- mutates `fail_mode` post-construction | Add `__slots__` to `PetasosConfig` (prevents `__dict__` mutation) or add a `__setattr__` override that raises unconditionally |
| CFG-04 | medium | `object.__setattr__(config, 'TIER3_FLOOR', 5)` (on module) | `TIER3_FLOOR` is a module-level `float` constant -- technically reassignable | Make `TIER3_FLOOR` a `Final` type annotation. Validate `tier3_threshold >= 30.0` at runtime in `__post_init__` (already done). Add a runtime assertion in `evaluate_tier()` that `tier3 >= 30.0`. |
| CFG-05 | low | `object.__setattr__` on pipeline's config copy | Pipeline stores `config` via shallow copy; freeze bypass reaches pipeline internals | `copy.deepcopy(config)` at Pipeline construction + store in a `__slots__` attribute. Or: validate config hash at `inspect()` entry. |

## Approach

The root cause is Python's `object.__setattr__` bypass on frozen dataclasses. The standard defense is `__slots__=True`:

```python
@dataclass(frozen=True, slots=True)
class PetasosConfig:
    ...
```

`slots=True` (Python 3.10+) eliminates `__dict__`, making `object.__setattr__` fail with `AttributeError`. This single change fixes CFG-01.

For CFG-04: `TIER3_FLOOR` is a module-level constant; Python has no true constant enforcement. Add `typing.Final` annotation and a runtime guard in `evaluate_tier()` that asserts `config.tier3_threshold >= 30.0` (belt-and-suspenders with `__post_init__`).

For CFG-05: Replace `config` storage in `Pipeline.__init__` with `copy.deepcopy(config)` and mark the attribute in `__slots__`.

## Decisions carried forward

- **`slots=True` requires Python 3.10+:** Petasos already targets 3.11+, so this is safe.
- **Module-level constant mutability is a Python language limitation.** `typing.Final` is a static-analysis hint only. The runtime guard in `evaluate_tier()` is the real protection. Accepted: an attacker with code execution who can call `object.__setattr__` on module globals already has arbitrary code execution -- but the guard prevents *configuration-level* attacks via `from_dict` or profile injection.

## Done when

- [ ] `PetasosConfig` uses `slots=True` -- `object.__setattr__(config, "fail_mode", "open")` raises `AttributeError`
- [ ] `TIER3_FLOOR` annotated as `Final[float]` and `evaluate_tier()` has a runtime floor assertion
- [ ] Pipeline stores a `deepcopy` of config; mutating the original after construction has no effect
- [ ] >= 9 tests (3 per finding)
- [ ] `mypy --strict` clean
- [ ] No breakage in existing config serialization tests

## Out of scope

- Making all dataclasses across the codebase `slots=True` (can be a follow-up sweep)
- Hardware-level memory protection (out of Python's reach)
