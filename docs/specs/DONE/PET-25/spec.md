# PET-25 — Strict Bool Coercion in `from_dict` and `__post_init__`

**Ticket:** PET-25 (CFG-03) + PET-24 (CFG-02)  
**Brief:** `docs/briefs/PET-25-cfg-03-bool-coercion.md`  
**Priority:** High  
**OWASP:** ASI07 — System prompt and instruction manipulation

---

## Goal

Close the bool-coercion gap in `PetasosConfig` that allows non-bool falsy values (e.g., `0`, `""`, `None`) to silently disable safety-critical toggles, and non-bool truthy values (e.g., `1`, `"yes"`) to silently enable premium features. Both `from_dict` (the untrusted-config surface) and the dataclass constructor (via `__post_init__`) will reject non-bool values for all boolean toggle fields with `TypeError`.

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/config.py` | Add `_BOOL_FIELDS` frozenset constant; add `isinstance(val, bool)` enforcement in `from_dict` and at the top of `__post_init__` |
| `tests/test_config.py` | Add new test classes `TestBoolCoercion` and `TestBoolFieldsCoverage` (8 tests total) |
| `tests/adversarial/config/test_bool_coercion.py` | New file — adversarial parameterized tests (2 tests) |
| `tests/adversarial/config/test_config_poisoning.py` | Update `test_anonymize_truthy_non_bool_without_bool_check` to expect `TypeError` instead of demonstrating bypass |
| `tests/adversarial/pipeline/test_degraded_fail_open.py` | Update `test_from_dict_disables_normalization_via_falsy_zero` to expect `TypeError` instead of demonstrating bypass |

### Files to leave alone

- `petasos/pipeline.py` — no changes to how the pipeline reads config booleans; the fix is at the config boundary
- `petasos/normalize.py` — consumes config booleans but does not validate them
- All scanner files, premium modules — no boolean validation changes needed downstream

## Decisions

### Decision 1: `TypeError`, not `ValueError`

This is a type violation (wrong type for a typed field), not a range/value violation. The existing `__post_init__` validation uses `ValueError` for range checks (e.g., "must be positive and finite") and `isinstance(val, bool)` exclusion guards on int fields. Using `TypeError` for bool-field violations distinguishes the two error classes. The brief explicitly chose this.

### Decision 2: Reject, don't coerce

`bool(0)` produces `False` — exactly the attacker's intent. Silent coercion would mask the attack. Raising forces the caller to be explicit about the type. An `int` in a bool field is never a legitimate accident in serialized config.

### Decision 3: Both `from_dict` and `__post_init__`

`from_dict` is the primary untrusted surface, but `__post_init__` catches direct constructor misuse (`PetasosConfig(normalize_nfkc=0)`). This matches the existing defense-in-depth pattern used by alerting integer fields (e.g., L157–165: `not isinstance(self.alert_per_minute_cap, int) or isinstance(self.alert_per_minute_cap, bool)`).

### Decision 4: CFG-02 and CFG-03 are one fix

Truthy-non-bool (CFG-02) and falsy-non-bool (CFG-03) are the same coercion gap. Splitting them would produce identical code. PET-24 and PET-25 ship together.

### Decision 5: `_BOOL_FIELDS` as a frozenset with mechanical coverage test

Adding a new boolean toggle to `PetasosConfig` requires adding it to `_BOOL_FIELDS`. A `test_all_bool_fields_covered` test enforces this mechanically by introspecting the dataclass field type annotations.

### Decision 6: Error message format simplified from brief

The brief used `f"{key} must be a bool, got {type(val).__name__}: {val!r}"` (includes type name before repr). This spec simplifies to `f"{key} must be a bool, got {val!r}"` to match the existing `__post_init__` validation pattern (e.g., `f"direction must be 'inbound' or 'outbound', got {self.direction!r}"`).

## Design

### 1. `_BOOL_FIELDS` constant (`petasos/config.py`, module level)

Add a `frozenset` before the `PetasosConfig` class definition:

```python
_BOOL_FIELDS: frozenset[str] = frozenset({
    "normalize_nfkc",
    "strip_zero_width",
    "map_homoglyphs",
    "detect_rtl_override",
    "anonymize",
    "frequency_enabled",
    "escalation_enabled",
    "tool_guard_enabled",
    "audit_enabled",
    "alert_enabled",
})
```

This is the single source of truth for which fields receive bool enforcement. Positioned at module scope so both `from_dict` and `__post_init__` reference it, and tests can import it for coverage assertions.

### 2. `from_dict` enforcement (`petasos/config.py`, ~L272–278)

After the existing `pii_entities` coercion and before `return cls(**filtered)`, iterate `_BOOL_FIELDS` and reject non-bool values:

```python
@classmethod
def from_dict(cls, data: dict[str, Any]) -> PetasosConfig:
    known = {f.name for f in fields(cls)}
    filtered = {k: v for k, v in data.items() if k in known}
    if "pii_entities" in filtered and isinstance(filtered["pii_entities"], list):
        filtered["pii_entities"] = tuple(filtered["pii_entities"])
    for key in _BOOL_FIELDS:
        if key in filtered and not isinstance(filtered[key], bool):
            raise TypeError(
                f"{key} must be a bool, got {filtered[key]!r}"
            )
    return cls(**filtered)
```

The error message format `f"{field} must be a bool, got {val!r}"` matches the existing `__post_init__` validation pattern (see Decision 6). The loop raises on the first invalid field encountered; iteration order over the frozenset is non-deterministic, which is acceptable for a security boundary (fail fast).

The check only fires when the key is present in `filtered` — omitted keys fall through to dataclass defaults (which are already `bool`). This preserves the existing behavior where `from_dict({"direction": "outbound"})` fills defaults for all unspecified fields.

### 3. `__post_init__` defense-in-depth (`petasos/config.py`, top of `__post_init__`)

Insert at the very top of `__post_init__` (before the existing `pii_entities` tuple coercion at L84):

```python
def __post_init__(self) -> None:
    for fname in _BOOL_FIELDS:
        val = getattr(self, fname)
        if not isinstance(val, bool):
            raise TypeError(
                f"{fname} must be a bool, got {val!r}"
            )
    # ... existing validation continues unchanged ...
```

This catches `PetasosConfig(normalize_nfkc=0)` — the direct-constructor path that bypasses `from_dict`.

### 4. Update existing adversarial tests

Two existing adversarial tests exercise the bypass being closed and must be updated:

**a) `tests/adversarial/config/test_config_poisoning.py::test_anonymize_truthy_non_bool_without_bool_check`**

Currently constructs `PetasosConfig(anonymize=1)` and asserts the bypass succeeds. Update to expect `TypeError`:

```python
def test_anonymize_truthy_non_bool_rejected() -> None:
    """CFG-02: int 1 for anonymize is now rejected by __post_init__."""
    with pytest.raises(TypeError, match="anonymize must be a bool"):
        PetasosConfig(anonymize=1)  # type: ignore[arg-type]
```

**b) `tests/adversarial/pipeline/test_degraded_fail_open.py::test_from_dict_disables_normalization_via_falsy_zero`**

Currently constructs `PetasosConfig.from_dict({"normalize_nfkc": 0})` and asserts `not cfg.normalize_nfkc` (demonstrating the bypass). Update to expect `TypeError`. The `@pytest.mark.asyncio` decorator can be dropped since the test no longer awaits anything. Rename to reflect new semantics:

```python
def test_from_dict_rejects_normalize_nfkc_falsy_zero() -> None:
    """CFG-03 / PIPE-05: normalize_nfkc=0 in from_dict now rejected."""
    with pytest.raises(TypeError, match="normalize_nfkc must be a bool"):
        PetasosConfig.from_dict({"normalize_nfkc": 0})
```

## Test plan

The brief specified 9 tests; this spec adds `test_from_dict_all_toggles_truthy_non_bool` for symmetric coverage (the brief only parameterized falsy values) and explicitly counts two regression-guard updates, bringing the total to 12.

### Unit tests (`tests/test_config.py` — added to existing file as new classes)

| # | Test name | Class | What it asserts |
|---|-----------|-------|-----------------|
| 1 | `test_from_dict_rejects_int_zero_for_bool` | `TestBoolCoercion` | `from_dict({"normalize_nfkc": 0})` raises `TypeError` |
| 2 | `test_from_dict_rejects_int_one_for_bool` | `TestBoolCoercion` | `from_dict({"escalation_enabled": 1})` raises `TypeError` |
| 3 | `test_from_dict_rejects_string_for_bool` | `TestBoolCoercion` | `from_dict({"audit_enabled": "true"})` raises `TypeError` |
| 4 | `test_from_dict_rejects_none_for_bool` | `TestBoolCoercion` | `from_dict({"strip_zero_width": None})` raises `TypeError` |
| 5 | `test_from_dict_accepts_true_bool` | `TestBoolCoercion` | `from_dict({"normalize_nfkc": True})` succeeds, value is `True` |
| 6 | `test_from_dict_accepts_false_bool` | `TestBoolCoercion` | `from_dict({"normalize_nfkc": False})` succeeds, value is `False` |
| 7 | `test_direct_constructor_rejects_int_for_bool` | `TestBoolCoercion` | `PetasosConfig(normalize_nfkc=0)` raises `TypeError` |

### Coverage test (`tests/test_config.py`)

| # | Test name | Class | What it asserts |
|---|-----------|-------|-----------------|
| 8 | `test_all_bool_fields_covered` | `TestBoolFieldsCoverage` | Every field in `PetasosConfig` with a `bool` type annotation appears in `_BOOL_FIELDS`, and vice versa |

Implementation note: `petasos/config.py` uses `from __future__ import annotations`, which stringifies type annotations at runtime. `typing.get_type_hints(PetasosConfig)` will crash with `NameError` because `Direction` and `Mapping` are imported under `if TYPE_CHECKING:` and absent at runtime. Use string comparison on `dataclasses.fields()` instead:

```python
from dataclasses import fields
annotated_bools = {f.name for f in fields(PetasosConfig) if f.type == "bool"}
assert annotated_bools == _BOOL_FIELDS
```

### Adversarial tests (`tests/adversarial/config/test_bool_coercion.py` — new file)

| # | Test name | What it asserts |
|---|-----------|-----------------|
| 9 | `test_from_dict_all_toggles_falsy_int` | Parameterized over `_BOOL_FIELDS`: `from_dict({field: 0})` raises `TypeError` for each |
| 10 | `test_from_dict_all_toggles_truthy_non_bool` | Parameterized over `_BOOL_FIELDS`: `from_dict({field: 1})` raises `TypeError` for each |

### Regression guards (updated existing tests)

| # | Test name | File | What it asserts |
|---|-----------|------|-----------------|
| 11 | `test_anonymize_truthy_non_bool_rejected` | `tests/adversarial/config/test_config_poisoning.py` | `PetasosConfig(anonymize=1)` now raises `TypeError` |
| 12 | `test_from_dict_rejects_normalize_nfkc_falsy_zero` | `tests/adversarial/pipeline/test_degraded_fail_open.py` | `from_dict({"normalize_nfkc": 0})` now raises `TypeError` |

### Existing tests

The existing `tests/test_config.py` tests (defaults, validation, serialization, frozen) must continue to pass unchanged. The round-trip test (`test_round_trip`) exercises `to_dict` -> `from_dict` with valid bool values and should not be affected.

## Test command

```bash
python -m pytest tests/test_config.py tests/adversarial/config/test_bool_coercion.py tests/adversarial/config/test_config_poisoning.py tests/adversarial/pipeline/test_degraded_fail_open.py -v
```

## Done when

- [ ] `_BOOL_FIELDS` frozenset constant defined in `petasos/config.py` at module scope
- [ ] `from_dict` raises `TypeError` for non-bool values in any `_BOOL_FIELDS` toggle
- [ ] `__post_init__` raises `TypeError` for non-bool values in any `_BOOL_FIELDS` toggle (defense-in-depth)
- [ ] All 12 tests listed above pass (7 unit + 1 coverage + 2 adversarial + 2 updated regressions)
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite (existing `tests/test_config.py` passes)
- [ ] PET-52 (PIPE-05) unblocked by this fix

## Deferred (P2+)

- **Container-type test cases (P3):** The test plan covers `int`, `str`, and `None` as non-bool values but not container types (`[]`, `{}`, `[1]`). The `isinstance(val, bool)` check rejects all of these correctly, but adversarial test coverage for containers is deferred.
- **`_BOOL_FIELDS` underscore-prefix vs test imports (P3):** Tests import the underscore-prefixed `_BOOL_FIELDS` constant. This is consistent with existing patterns (e.g., `test_config_poisoning.py` accesses `config_mod.TIER3_FLOOR`). If ruff flags private imports in tests, add `# noqa` comments.

## Out of scope

- JSON schema validation for config files (separate concern — config may come from YAML, TOML, or programmatic dict)
- Coercion of string-enum fields (`direction`, `fail_mode`, etc.) — already validated in `__post_init__`
- `from_dict` rejecting unknown keys (currently silently filtered; separate finding if needed)
- Drawbridge backport (TypeScript handles this differently)
- CFG-01 (frozen bypass via `object.__setattr__`) — separate finding, different mechanism
- CFG-04 (TIER3_FLOOR module-global mutability) — separate finding, different mechanism
