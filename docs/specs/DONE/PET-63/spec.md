# PET-63 — SCAN-05: Anonymize with Empty hash_key Falls Back to Unkeyed SHA-256

## Goal

Eliminate the unkeyed SHA-256 anonymization path and reject empty `hash_key` strings in both the `anonymize()` function and the `_HmacSha256Operator`. When `mode="hash"`, a non-empty `hash_key` is mandatory — callers who omit it or pass an empty string get a `ValueError`, not a silently reversible digest.

## Scope

### Files changed

| File | Change |
|------|--------|
| `petasos/scanners/presidio.py` | Add `hash_key` guard in `anonymize()`, reject empty key in `_HmacSha256Operator.validate()`, remove unkeyed SHA-256 fallback in `_anonymize_engine_path()` |
| `petasos/config.py` | Tighten `hash_key` validation to reject empty strings |
| `tests/test_presidio_scanner.py` | Update `test_hash_without_key_uses_sha256` to expect `ValueError`, add new tests for empty key rejection |
| `tests/test_config.py` | Add test for empty-string `hash_key` rejection at config level |

### Files left alone

- `petasos/pipeline.py` — `Pipeline` calls `anonymize()` with `config.hash_key`; the config-level guard ensures it never passes `None` or `""` when `mode="hash"` and `anonymize=True`. If the guard were bypassed, the pipeline's `except Exception` at L444 would catch the `ValueError` and append it to `PipelineResult.errors` — PII would remain unsanitized but the pipeline would not throw, preserving the "pipeline never throws" invariant. This is the expected degradation path, not a gap
- `petasos/scanners/minimal.py`, `petasos/scanners/llm_guard.py`, `petasos/scanners/llama_firewall.py` — unrelated scanners
- `petasos/premium/` — premium modules not involved

## Decisions

### D1: Raise ValueError, not silent fallback

**Honors brief decision: "Raise, not silent fallback."** The current unkeyed SHA-256 fallback creates a false sense of security. Callers who specify `mode="hash"` expect irreversibility — they should provide a key or get an explicit error. `ValueError` is the standard Python convention for invalid parameters, and `anonymize()` is a post-scan utility outside the scanner protocol's "never throw" contract.

### D2: Guard at anonymize() entry, not just the operator

The `_HmacSha256Operator.validate()` check catches empty keys for the HMAC path, but the unkeyed SHA-256 fallback in `_anonymize_engine_path()` never reaches the operator at all — it uses Presidio's built-in `hash` operator. The fix places the primary guard in `anonymize()` at function entry, before any PII processing occurs. The operator-level check is a secondary defense-in-depth layer.

### D3: Remove the unkeyed SHA-256 fallback entirely

After the `anonymize()` guard, the `else` branch in `_anonymize_engine_path()` (L267-269) that constructs an unkeyed `OperatorConfig("hash", ...)` is unreachable. Remove it and replace with an explicit `if not hash_key: raise ValueError(...)` guard. This prevents future internal callers of `_anonymize_engine_path()` from accidentally hitting the insecure path.

Note: The brief recommended `assert hash_key`, but PET-10 review round 1 flagged bare `assert` as P1 because `python -O` strips assertions. Although this is defense-in-depth behind the `anonymize()` guard, we use an explicit raise to survive optimization mode — consistent with the PET-10 resolution. The existing `assert finding.position is not None` uses in `presidio.py` (L202, L203, L248) are internal precondition checks with different risk profiles.

### D4: Config-level empty-string rejection

The existing `PetasosConfig.__post_init__()` validation at L129-130 checks `hash_key is None` but not `hash_key == ""`. Tighten to `not hash_key` (catches both `None` and empty string). This is the outermost defense — pipeline consumers hit this before `anonymize()` is ever called.

### D5: Empty string is not a key

**Honors brief decision: "Empty string is not a key."** `HMAC(b"", data)` is a known degenerate case that provides no secrecy. Both the `anonymize()` guard and the operator-level validation reject it.

## Design

### Layer 1: Config-level guard (outermost)

In `PetasosConfig.__post_init__()`, change the existing check:

```python
# Before (L129-130):
if self.anonymize and self.redaction_mode == "hash" and self.hash_key is None:
    raise ValueError("hash_key is required when redaction_mode='hash' and anonymize=True")

# After:
if self.anonymize and self.redaction_mode == "hash" and not self.hash_key:
    raise ValueError("hash_key is required and must be non-empty when redaction_mode='hash' and anonymize=True")
```

This catches `hash_key=None`, `hash_key=""`, and any other falsy string at config construction time. Pipeline consumers never reach `anonymize()` with an invalid key.

### Layer 2: anonymize() entry guard

Add validation at the top of `anonymize()`, after the `positioned` filter but before dispatching to engine/manual paths:

```python
if mode == "hash" and not hash_key:
    raise ValueError(
        "hash_key is required and must be non-empty for mode='hash'. "
        "Unkeyed hashing is reversible on low-entropy PII."
    )
```

This catches direct callers of `anonymize()` who bypass `PetasosConfig` (e.g., test code, library consumers using `anonymize()` standalone).

### Layer 3: _HmacSha256Operator.validate() (defense-in-depth)

Add empty-string check after the existing type check:

```python
def validate(self, params: dict[str, Any] | None = None) -> None:
    if not params or not isinstance(params.get("hmac_key"), str):
        raise ValueError("hmac_key (str) is required")
    if not params["hmac_key"]:
        raise ValueError("hmac_key must be non-empty")
```

### Layer 4: Remove unkeyed SHA-256 fallback

In `_anonymize_engine_path()`, replace the `if/else` block inside `elif mode == "hash":`:

```python
# Before (L263-269):
elif mode == "hash":
    if hash_key is not None:
        for et in entity_types_seen:
            operators[et] = OperatorConfig("hmac_sha256", {"hmac_key": hash_key})
    else:
        for et in entity_types_seen:
            operators[et] = OperatorConfig("hash", {"hash_type": "sha256"})

# After:
elif mode == "hash":
    if not hash_key:
        raise ValueError("hash_key must be non-empty (enforced by anonymize())")
    for et in entity_types_seen:
        operators[et] = OperatorConfig("hmac_sha256", {"hmac_key": hash_key})
```

## Test plan

### Unit tests — `tests/test_presidio_scanner.py`

| # | Test | Class | Asserts |
|---|------|-------|---------|
| 1 | `test_hash_mode_requires_key` | `TestAnonymizeHash` | `anonymize(..., mode="hash")` with no `hash_key` raises `ValueError` matching "hash_key" |
| 2 | `test_hash_mode_rejects_empty_key` | `TestAnonymizeHash` | `anonymize(..., mode="hash", hash_key="")` raises `ValueError` matching "hash_key" |
| 3 | `test_hash_mode_with_valid_key_works` | `TestAnonymizeHash` | `anonymize(..., mode="hash", hash_key="secret")` succeeds and replaces PII (already covered by `test_hmac_deterministic`, but brief lists it explicitly) |
| 4 | `test_hmac_operator_rejects_empty_key` | `TestAnonymizeHash` | Obtain class via `_make_hmac_operator_class()`, then `cls().validate({"hmac_key": ""})` raises `ValueError` matching "non-empty" |
| 5 | `test_hmac_operator_rejects_missing_key` | `TestAnonymizeHash` | Obtain class via `_make_hmac_operator_class()`, then `cls().validate({})` raises `ValueError` |
| 6 | `test_redact_mode_ignores_hash_key` | `TestAnonymizeHash` | `anonymize(..., mode="redact", hash_key=None)` works without error |
| 7 | Update `test_hash_without_key_uses_sha256` | `TestAnonymizeHash` | Change from asserting success to asserting `ValueError` is raised |

### Unit tests — `tests/test_config.py`

| # | Test | Asserts |
|---|------|---------|
| 8 | `test_rejects_empty_hash_key_for_hash_mode` | `PetasosConfig(anonymize=True, redaction_mode="hash", hash_key="")` raises `ValueError` matching "hash_key" |

### Mapping to brief's required tests

| Brief Test | Covered By |
|------------|------------|
| `test_hash_mode_requires_key` | Test 1 |
| `test_hash_mode_rejects_empty_key` | Test 2 |
| `test_hash_mode_with_valid_key_works` | Test 3 (plus existing `test_hmac_deterministic`) |
| `test_hmac_operator_rejects_empty_key` | Test 4 |
| `test_hmac_operator_rejects_missing_key` | Test 5 |
| `test_redact_mode_ignores_hash_key` | Test 6 |
| Update `test_hash_without_key_uses_sha256` | Test 7 |

## Test command

```
python -m pytest tests/test_presidio_scanner.py tests/test_config.py -v
```

## Done when

- [ ] `anonymize()` raises `ValueError` when `mode="hash"` and `hash_key` is `None` or empty
- [ ] `_HmacSha256Operator.validate()` rejects empty `hmac_key`
- [ ] Unkeyed SHA-256 fallback path removed from `_anonymize_engine_path()`
- [ ] Config-level validation rejects empty `hash_key`
- [ ] All 8 tests listed above pass (6 new + 1 updated + 1 config)
- [ ] `test_hash_without_key_uses_sha256` updated to assert `ValueError`
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of scope

- Key rotation or key management (operators manage their own keys externally)
- Minimum key length enforcement (any non-empty string is accepted, including whitespace-only strings; key strength is the operator's responsibility)
- Alternative hash algorithms beyond SHA-256 (not currently supported)
- Drawbridge backport (Drawbridge already handles this correctly)
