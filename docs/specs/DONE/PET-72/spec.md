# PET-72 — Types Validation (TYP-02 / TYP-03 / TYP-04)

**Plane:** PET-72, PET-73, PET-74 · **Findings:** TYP-02, TYP-03, TYP-04 · **Priority:** Medium
**Parent:** PET-14 · **Blocks:** PET-12 (release)

---

## Goal

Harden the core type layer (`petasos/_types.py`) with construction-time validation and structural scanner verification. `Position` rejects inverted/negative spans, `ScanFinding` rejects out-of-range confidence (including NaN/inf), `PipelineResult` enforces `MappingProxyType` wrapping on `premium_features`, and a new `_validate_scanner()` function catches non-conforming scanner objects at `Pipeline` registration rather than at first `await`.

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/_types.py` | Add `__post_init__` to `Position`, `ScanFinding`, `PipelineResult`; promote `MappingProxyType` to runtime import and remove `TYPE_CHECKING` from typing imports; add `_validate_scanner()` function; add `import inspect` |
| `petasos/pipeline.py` | Import and call `_validate_scanner()` for each scanner in `Pipeline.__init__` |

### Files to create

| File | Purpose |
|------|---------|
| `tests/adversarial/types/test_type_validation.py` | 17 tests covering all three findings |

No `__init__.py` in `tests/adversarial/types/` — matching the majority convention of adversarial test subdirectories (only `frequency/` has one; all others omit it). Pytest discovers tests via rootdir.

### Files to leave alone

- `petasos/__init__.py` — `_validate_scanner` is a private helper (underscore prefix); no public API export needed
- `petasos/config.py` — CFG-01 slots hardening is Brief 3; no overlap
- `petasos/scanners/*.py` — scanner internals unchanged; validation targets the protocol boundary
- `petasos/premium/*.py` — premium modules unaffected
- `tests/test_types.py` — existing frozen/roundtrip tests remain valid; new tests are adversarial-focused and go under `tests/adversarial/types/` matching PET-14 remediation patterns

## Decisions

### Decision 1: TYP-02 scoped to `PipelineResult.premium_features` only

The brief describes "mutate dict inside ScanFinding via retained reference" and names `payload`, `context`, `premium_features` as the vulnerable fields. In the current codebase:

- `ScanFinding` has **no dict fields** — all fields are `str`, `float`, `Severity` (enum), `Position | None`, `str | None`. No dict mutation is possible.
- `AuditEvent.payload` and `Alert.context` use `MappingProxyType` in their type annotations, but the brief explicitly marks them **out of scope** ("emitted internally, not from untrusted input").
- `PipelineResult.premium_features: MappingProxyType[str, str] | None` is the only in-scope field where a caller could pass a plain `dict` and retain a mutable reference.

The `__post_init__` on `PipelineResult` wraps `premium_features` in `MappingProxyType(dict(...))` if a plain dict is passed. This is defense-in-depth — `Pipeline._build_premium_features()` already returns `MappingProxyType`, but the guard protects against direct construction. The wrapping is shallow (`MappingProxyType` only prevents top-level key mutation); this is sufficient because the current type annotation constrains values to `str`, which is immutable.

### Decision 2: Confidence raises, not clamps

The brief says "clamping in `ScanFinding.__post_init__` means invalid confidence raises at construction, not silently." This is the correct interpretation: `__post_init__` raises `ValueError` for `confidence` outside `[0.0, 1.0]`, rather than silently clamping. Fail-loud is appropriate for a security type — silent clamping could mask bugs in scanner implementations. Brief 8's SCAN-02 per-scanner clamp (`max(0.0, min(1.0, raw))`) is separate defense-in-depth at the scanner wrapper layer.

NaN and inf values are also rejected: `not (0.0 <= float('nan') <= 1.0)` evaluates to `True` because NaN comparisons always return `False`. `float('inf')` fails the upper bound. Both raise `ValueError`.

### Decision 3: `_validate_scanner()` — private, checks signature at registration, not return type at call time

Per the brief: "We validate signature at registration, not return type at call time." The function checks:
1. Has `name` attribute (property or plain attribute)
2. Has `scan` attribute that is callable and async (`inspect.iscoroutinefunction`)
3. `scan` signature contains `text`, `direction`, and `session_id` parameters (`inspect.signature`) — unless `scan` accepts `**kwargs`, in which case keyword parameter checks are skipped

Named `_validate_scanner` (private, underscore prefix) — it is an internal helper called only by `Pipeline.__init__`, not a public API. This matches the pattern of `_is_missing_package` in `petasos/scanners/__init__.py`.

### Decision 4: Negative position start — spec addition beyond brief

The brief specifies inverted-span rejection (`start > end`). This spec additionally rejects negative start indices (`start < 0`), which are semantically invalid for text positions. Zero-length positions (`start == end`) are valid — they represent cursor positions or insertion points.

## Design

### 1. `MappingProxyType` import promotion

Move `from types import MappingProxyType` from the `TYPE_CHECKING` block to a regular import. The file has `from __future__ import annotations` (line 1), which makes all annotations lazy strings at runtime — so the `TYPE_CHECKING` import sufficed for annotations alone. The new `PipelineResult.__post_init__` uses `MappingProxyType` at actual runtime (`isinstance` check and constructor call), requiring a real import.

```python
# Before (lines 5, 7-8):
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from types import MappingProxyType

# After:
from types import MappingProxyType
from typing import Any, Literal, Protocol, runtime_checkable
```

`TYPE_CHECKING` is removed from the `typing` import line because no `if TYPE_CHECKING:` block remains. Without this cleanup, `ruff check` flags F401 (`TYPE_CHECKING` imported but unused).

### 2. `Position.__post_init__` (TYP-03)

```python
@dataclass(frozen=True)
class Position:
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError(f"Position.start must be >= 0, got {self.start}")
        if self.end < self.start:
            raise ValueError(
                f"Position.end ({self.end}) must be >= Position.start ({self.start})"
            )
```

### 3. `ScanFinding.__post_init__` (TYP-03)

```python
@dataclass(frozen=True)
class ScanFinding:
    # ... existing fields ...

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"ScanFinding.confidence must be in [0.0, 1.0], got {self.confidence}"
            )
```

Boundary values 0.0 and 1.0 are both accepted. NaN and inf are rejected by comparison semantics.

### 4. `PipelineResult.__post_init__` (TYP-02)

```python
@dataclass(frozen=True)
class PipelineResult:
    # ... existing fields ...

    def __post_init__(self) -> None:
        pf = self.premium_features
        if pf is not None and not isinstance(pf, MappingProxyType):
            object.__setattr__(
                self, "premium_features", MappingProxyType(dict(pf))
            )
```

Uses `object.__setattr__` — the standard pattern for modifying fields in frozen dataclass `__post_init__`. Makes a defensive copy via `dict(pf)` to sever any retained reference to the original dict.

### 5. `_validate_scanner()` function (TYP-04)

Add to `_types.py` after the `Scanner` protocol definition. Insert `import inspect` in the stdlib import section (after `import enum`, before `from dataclasses import dataclass`).

```python
def _validate_scanner(obj: Any) -> None:
    """Structural validation beyond @runtime_checkable isinstance check.

    Raises TypeError if obj does not conform to the Scanner protocol."""
    try:
        has_name = hasattr(obj, "name")
    except Exception as exc:
        raise TypeError(
            f"Scanner {type(obj).__name__!r}: accessing 'name' raised "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    if not has_name:
        raise TypeError(
            f"Scanner object {type(obj).__name__!r} missing 'name' attribute"
        )

    scan = getattr(obj, "scan", None)
    if scan is None or not callable(scan):
        raise TypeError(
            f"Scanner object {type(obj).__name__!r} missing callable 'scan' method"
        )

    if not inspect.iscoroutinefunction(scan):
        raise TypeError(
            f"Scanner {type(obj).__name__!r}.scan() must be async"
        )

    try:
        sig = inspect.signature(scan)
    except (ValueError, TypeError) as exc:
        raise TypeError(
            f"Scanner {type(obj).__name__!r}.scan(): cannot introspect signature: {exc}"
        ) from exc

    params = sig.parameters
    has_var_keyword = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
    )
    if not has_var_keyword:
        param_names = set(params.keys())
        for required in ("text", "direction", "session_id"):
            if required not in param_names:
                raise TypeError(
                    f"Scanner {type(obj).__name__!r}.scan() missing "
                    f"'{required}' parameter"
                )
```

Key design choices:
- **`**kwargs` handling:** If `scan` accepts `**kwargs`, keyword parameter name checks are skipped — `**kwargs` implicitly accepts all keyword arguments including `direction` and `session_id`.
- **Property exception wrapping:** `hasattr` can propagate non-`AttributeError` exceptions from property accessors. Wrapping in try/except produces a clear `TypeError` instead of an opaque propagated exception.
- **`inspect.signature` failure handling:** C extensions, `functools.partial`, and exotic callables can cause `ValueError`. Wrapped and re-raised as `TypeError` for consistent error typing.

### 6. Pipeline integration (TYP-04)

In `pipeline.py`, add `_validate_scanner` to the existing `from petasos._types import (...)` block at line 12 (inserted alphabetically). Then call it for each scanner in `__init__`:

```python
# Add to existing import block (pipeline.py line 12):
from petasos._types import (
    Alert,
    AuditEvent,
    PipelineResult,
    ScanFinding,
    ScanResult,
    Severity,
    _validate_scanner,
)

class Pipeline:
    def __init__(self, scanners: Sequence[Scanner] = (), ...) -> None:
        # ... existing code up to scanner_list ...
        scanner_list = list(scanners)

        for s in scanner_list:
            _validate_scanner(s)

        # ... rest of existing scanner classification logic ...
```

The validation runs once at construction, before the scanner is classified as minimal vs. ML. This catches invalid objects before they enter the hot path.

Note: `_validate_scanner` raises at construction time. The "Pipeline never throws" invariant applies to `inspect()` (the hot path), not `__init__()`. This is consistent with the existing `ValueError` for missing `host_id` (`pipeline.py` line 186).

## Test plan

All tests in `tests/adversarial/types/test_type_validation.py`. Organized by finding.

### TYP-02: `PipelineResult` immutability enforcement (4 tests)

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_pipeline_result_dict_wrapped_as_proxy` | `PipelineResult(premium_features={"k": "v"}, ...)` stores a `MappingProxyType`, not a `dict` |
| 2 | `test_pipeline_result_proxy_mutation_raises` | Mutating `result.premium_features["k"]` raises `TypeError` |
| 3 | `test_pipeline_result_none_stays_none` | `PipelineResult(premium_features=None, ...)` keeps `None` |
| 4 | `test_pipeline_result_proxy_not_double_wrapped` | Passing `MappingProxyType({"k": "v"})` stays as-is (no double-wrapping) |

### TYP-03: Position + confidence validation (7 tests)

| # | Test | Asserts |
|---|------|---------|
| 5 | `test_position_inverted_raises` | `Position(start=10, end=5)` raises `ValueError` |
| 6 | `test_position_negative_start_raises` | `Position(start=-1, end=5)` raises `ValueError` |
| 7 | `test_position_zero_length_accepted` | `Position(start=5, end=5)` succeeds |
| 8 | `test_confidence_above_one_raises` | `ScanFinding(confidence=1.5, ...)` raises `ValueError` |
| 9 | `test_confidence_below_zero_raises` | `ScanFinding(confidence=-0.1, ...)` raises `ValueError` |
| 10 | `test_confidence_nan_raises` | `ScanFinding(confidence=float('nan'), ...)` raises `ValueError` |
| 11 | `test_confidence_inf_raises` | `ScanFinding(confidence=float('inf'), ...)` raises `ValueError` |

### TYP-04: Scanner validation (6 tests)

| # | Test | Asserts |
|---|------|---------|
| 12 | `test_validate_scanner_accepts_valid` | `_validate_scanner(MinimalScanner())` does not raise |
| 13 | `test_validate_scanner_missing_name` | Object without `name` -> `TypeError` |
| 14 | `test_validate_scanner_missing_scan` | Object with `name` but no `scan` -> `TypeError` |
| 15 | `test_validate_scanner_sync_scan_rejected` | Object with sync `scan` method -> `TypeError` |
| 16 | `test_validate_scanner_accepts_kwargs_scan` | Scanner with `async def scan(self, text, **kwargs)` -> accepted (no raise) |
| 17 | `test_pipeline_rejects_invalid_scanner` | `Pipeline(scanners=[invalid])` raises `TypeError` |

### Cross-cutting (1 test)

| # | Test | Asserts |
|---|------|---------|
| 18 | `test_from_dict_roundtrip_preserves_validation` | `ScanFinding.from_dict(finding.to_dict())` still enforces confidence bounds and position validation through construction |

### Existing test impact

None. Existing tests in `tests/test_types.py` construct valid objects — all existing `Position`, `ScanFinding`, `ScanResult`, and `PipelineResult` constructions use valid values. No existing test should break.

## Test command

```
py -3.13 -m pytest tests/adversarial/types/test_type_validation.py -v && py -3.13 -m pytest --tb=short -q && ruff check . && ruff format --check . && mypy --strict .
```

## Done when

- [ ] Mutating `premium_features` dict on a constructed `PipelineResult` raises `TypeError`
- [ ] `Position(start=10, end=5)` raises `ValueError`
- [ ] `ScanFinding(confidence=1.5)` raises `ValueError`
- [ ] Passing a non-conforming object as a scanner to `Pipeline()` raises `TypeError`
- [ ] `from_dict` round-trip preserves immutability (constructed -> to_dict -> from_dict -> still validated)
- [ ] >= 18 tests pass (4 TYP-02 + 7 TYP-03 + 6 TYP-04 + 1 cross-cutting)
- [ ] `mypy --strict` clean
- [ ] No regression in existing types or pipeline tests

## Deferred (P2+)

- **Brief Done When #1 references ScanFinding dict fields (P2):** Brief says "Mutating a dict field on a constructed ScanFinding raises TypeError", but `ScanFinding` has no dict fields in the current codebase. The spec scopes TYP-02 to `PipelineResult.premium_features` — the only in-scope mutable-map field. Brief Done-when #1 is not implementable as stated; see Decision 1 for rationale.
- **AuditEvent/Alert __post_init__ (P3):** Brief explicitly marks these out of scope. They already use `MappingProxyType` type annotations and are emitted internally.
- **_validate_scanner return-type checking (P3):** Not implemented per Decision 3. Integration tests are the right layer for return-type verification.
- **Brief test count (P4):** Brief Done When says ">= 12 tests (4 per finding)"; spec has 18. Additional tests cover NaN/inf confidence, positive scanner validation, **kwargs acceptance, and zero-length position acceptance. Spec Done When is authoritative.
- **Position float type enforcement (P3):** Python dataclasses do not enforce type annotations at runtime. `Position(start=0.5, end=5.5)` would pass range validation but fail downstream at string slicing. Mypy catches this statically; runtime type checking deferred.
- **_validate_scanner defensive refinements (P3):** Three defense-in-depth additions beyond the brief's literal specification: `**kwargs` bypass (skips keyword checks for scanners using `**kwargs`), property-exception wrapping (`hasattr` try/except), and `inspect.signature` failure handling (`ValueError`/`TypeError` wrapping). All are reasonable hardening for a validation function that handles arbitrary objects.
- **Error-path tests for _validate_scanner (P2):** Tests for `inspect.signature` failure and property-exception wrapping paths are omitted. These defensive paths handle exotic/pathological inputs and are covered by the try/except wrapping. Adding these tests is a P2 improvement.

## Out of scope

- Runtime return-type checking on every `scan()` invocation
- Retrofitting `__post_init__` to `AuditEvent` / `Alert` (emitted internally, not from untrusted input)
- Config immutability (`slots=True`, Brief 3 / PET-23)
- Per-scanner confidence clamping (Brief 8 / PET-60 SCAN-02)
