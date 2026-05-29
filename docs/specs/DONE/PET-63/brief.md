# PET-63 — SCAN-05: Anonymize with Empty hash_key Falls Back to Unkeyed SHA-256

**Plane:** PET-63 · **Finding:** SCAN-05 · **Priority:** High  
**OWASP:** ASI01 — Insecure output handling  
**Parent:** PET-14 · **Blocks:** PET-12 (release)  
**Status:** refuted → ready-for-dev

---

## Problem

The `anonymize()` function in `petasos/scanners/presidio.py` supports `mode="hash"` with an optional `hash_key` parameter. Two weaknesses exist in the hash path at `_anonymize_engine_path` (L233–276):

**1. Empty string accepted as a valid key (L264–266).**

```python
if hash_key is not None:
    for et in entity_types_seen:
        operators[et] = OperatorConfig("hmac_sha256", {"hmac_key": hash_key})
```

The check is `hash_key is not None`, so `hash_key=""` passes through. An HMAC keyed with an empty string is cryptographically degenerate — it reduces to `HMAC(b"", data)` which provides no secrecy. The `_HmacSha256Operator.validate()` method at L68–70 does check `if not params or not isinstance(params.get("hmac_key"), str)`, but this accepts empty strings since `isinstance("", str)` is `True`.

**2. Fallback to unkeyed SHA-256 is reversible on low-entropy PII (L267–269).**

```python
else:
    for et in entity_types_seen:
        operators[et] = OperatorConfig("hash", {"hash_type": "sha256"})
```

When `hash_key is None`, the code falls back to Presidio's built-in `hash` operator, which computes a plain `SHA-256(pii_value)`. For low-entropy PII (phone numbers, SSNs, dates, ZIP codes), this is trivially reversible via rainbow tables or brute-force enumeration. A US phone number has ~10^10 candidates; a SSN has ~10^9. Both are enumerable in seconds.

The existing test `test_hash_without_key_uses_sha256` (`tests/test_presidio_scanner.py:251–255`) confirms the unkeyed path works but does not flag the security gap.

## Prior Art

Drawbridge (TypeScript) guards this in `src/sanitize/index.ts:21`: `if (!config.hashRedactions || !config.hmacKey) return ""` — it returns an empty string (no hash) when no key is provided, refusing to produce a reversible digest. Drawbridge's test suite (`src/sanitize/__tests__/sanitize.test.ts:562`) explicitly tests that missing `hmacKey` produces an empty `contentHash`.

Petasos should adopt a stricter stance: require a non-empty key for hash mode, and reject empty keys at the operator level.

## Remediation

### Approach: Require non-empty hash_key for mode="hash"; reject empty strings

### Changes

**1. `petasos/scanners/presidio.py` — `anonymize()` (~L216–231)**

Add validation at the top of `anonymize()` when `mode="hash"`:

```python
if mode == "hash" and not hash_key:
    raise ValueError(
        "hash_key is required and must be non-empty for mode='hash'. "
        "Unkeyed hashing is reversible on low-entropy PII."
    )
```

This fails loud at the call site, before any PII processing occurs.

**2. `petasos/scanners/presidio.py` — `_HmacSha256Operator.validate()` (L68–70)**

Strengthen the existing validation to reject empty strings:

```python
def validate(self, params: dict[str, Any] | None = None) -> None:
    if not params or not isinstance(params.get("hmac_key"), str):
        raise ValueError("hmac_key (str) is required")
    if not params["hmac_key"]:
        raise ValueError("hmac_key must be non-empty")
```

**3. `petasos/scanners/presidio.py` — `_anonymize_engine_path()` (L263–269)**

Remove the unkeyed SHA-256 fallback entirely. After the `anonymize()` guard in change 1, this path is unreachable, but remove it as defense-in-depth to prevent future callers of the internal function from hitting it:

```python
if mode == "hash":
    assert hash_key, "hash_key must be non-empty (enforced by anonymize())"
    for et in entity_types_seen:
        operators[et] = OperatorConfig("hmac_sha256", {"hmac_key": hash_key})
```

### Tests Required

| Test | File | Asserts |
|------|------|---------|
| `test_hash_mode_requires_key` | `tests/test_presidio_scanner.py` | `anonymize(..., mode="hash")` without `hash_key` raises `ValueError` |
| `test_hash_mode_rejects_empty_key` | `tests/test_presidio_scanner.py` | `anonymize(..., mode="hash", hash_key="")` raises `ValueError` |
| `test_hash_mode_with_valid_key_works` | `tests/test_presidio_scanner.py` | `anonymize(..., mode="hash", hash_key="secret")` succeeds and replaces PII |
| `test_hmac_operator_rejects_empty_key` | `tests/test_presidio_scanner.py` | `_HmacSha256Operator().validate({"hmac_key": ""})` raises `ValueError` |
| `test_hmac_operator_rejects_missing_key` | `tests/test_presidio_scanner.py` | `_HmacSha256Operator().validate({})` raises `ValueError` |
| `test_redact_mode_ignores_hash_key` | `tests/test_presidio_scanner.py` | `anonymize(..., mode="redact", hash_key=None)` works without error |

### What the existing test needs

`test_hash_without_key_uses_sha256` (L251–255) currently asserts the unkeyed path succeeds. After the fix, this test should be updated to assert `ValueError` is raised.

## Decisions Carried Forward

- **Raise, not silent fallback.** The current unkeyed SHA-256 fallback creates a false sense of security. Operators who call `mode="hash"` expect irreversibility — they should provide a key or get an explicit error. This follows the pattern from Drawbridge where missing `hmacKey` produces no hash at all.
- **ValueError, not a degraded ScanResult.** Anonymization is a post-scan operation called by the operator, not part of the scanner protocol's "never throw" contract. A `ValueError` for invalid parameters is the standard Python convention.
- **Empty string is not a key.** `HMAC(b"", data)` is a known degenerate case. The operator-level validation and the `anonymize()` guard both reject it.
- **No "warn and proceed" option.** For a security-critical operation like PII anonymization, warnings that let reversible hashes through are unacceptable. Hard fail is the only safe default.

## Done When

- [ ] `anonymize()` raises `ValueError` when `mode="hash"` and `hash_key` is `None` or empty
- [ ] `_HmacSha256Operator.validate()` rejects empty `hmac_key`
- [ ] Unkeyed SHA-256 fallback path removed from `_anonymize_engine_path()`
- [ ] All 6 tests listed above pass
- [ ] `test_hash_without_key_uses_sha256` updated to assert `ValueError`
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of Scope

- Key rotation or key management (operators manage their own keys externally)
- Minimum key length enforcement (any non-empty string is accepted; key strength is the operator's responsibility)
- Alternative hash algorithms beyond SHA-256 (not currently supported)
- Drawbridge backport (Drawbridge already handles this correctly)
