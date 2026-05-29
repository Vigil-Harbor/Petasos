# Brief 2 · Types Validation

**Plane items:** PET-72 (TYP-02), PET-73 (TYP-03), PET-74 (TYP-04)
**Files touched:** `petasos/_types.py`, `tests/test_types.py`, `tests/adversarial/types/`
**Priority:** medium (all three)
**Parent:** PET-14 (red-team security review)
**Blocks:** PET-12 (release)

### Findings

| ID | Severity | Attack | Current behavior | Remediation |
|----|----------|--------|------------------|-------------|
| TYP-02 | medium | Mutate dict inside ScanFinding via retained reference | `payload`, `context`, `premium_features` map fields are type-annotated but not coerced to immutable at construction | Wrap map-typed fields in `MappingProxyType(dict(...))` at `__post_init__` / `from_dict` |
| TYP-03 | medium | `from_dict` with inverted position (start > end) | `ScanFinding.from_dict` accepts `Position(start=10, end=5)` without validation | Add `__post_init__` to `Position`: `if self.start > self.end: raise ValueError` |
| TYP-04 | medium | Scanner protocol object returning `str` instead of `ScanResult` | `@runtime_checkable` only checks method presence, not signatures or return types | Add `_validate_scanner(scanner)` helper that does a structural check (callable `scan`, correct signature) at Pipeline registration time |

### Approach

- **TYP-02:** Add `__post_init__` to `ScanFinding`, `ScanResult`, and `PipelineResult` that wraps any `dict` fields in `MappingProxyType(dict(field))`. The `frozen=True` dataclass already prevents field reassignment; this prevents mutation through the contained dict.
- **TYP-03:** Add `__post_init__` to `Position` dataclass: `if self.start < 0 or self.end < self.start: raise ValueError(...)`. Also clamp `confidence` in `ScanFinding.__post_init__` to `[0.0, 1.0]`.
- **TYP-04:** Add a `validate_scanner(obj) -> None` function that introspects beyond `isinstance`. Check: (a) has `name` property, (b) has async `scan` method, (c) smoke-call signature check via `inspect.signature`. Pipeline's `__init__` calls this for every registered scanner; raises `TypeError` on failure.

### Decisions carried forward

- **Structural validation depth for TYP-04:** We validate signature at registration, not return type at call time. Runtime return-type checking (wrapping every `scan()` call) adds overhead and is better caught by integration tests. The registration check catches the 80% case (wrong object passed in).
- **Confidence clamping location:** Clamping in `ScanFinding.__post_init__` means invalid confidence raises at construction, not silently. This is stricter than the SCAN-02 per-scanner clamp (Brief 8) — defense in depth.

### Done when

- [ ] Mutating a dict field on a constructed `ScanFinding` raises `TypeError`
- [ ] `Position(start=10, end=5)` raises `ValueError`
- [ ] `ScanFinding(confidence=1.5)` raises `ValueError`
- [ ] Passing a non-conforming object as a scanner to `Pipeline()` raises `TypeError`
- [ ] `from_dict` round-trip preserves immutability (constructed -> to_dict -> from_dict -> still immutable)
- [ ] >= 12 tests (4 per finding)
- [ ] `mypy --strict` clean

### Out of scope

- Runtime return-type checking on every `scan()` invocation
- Retrofitting `__post_init__` to `AuditEvent` / `Alert` (they're emitted internally, not from untrusted input)
