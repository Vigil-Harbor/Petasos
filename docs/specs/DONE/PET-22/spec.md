# PET-22 — AUD-03: Redact Secrets from Audit Payloads

**Plane:** PET-22 · **Finding:** AUD-03 · **Priority:** High
**Parent:** PET-14 · **Blocks:** PET-12 (release)

---

## Goal

Prevent `AuditEmitter._build_payload` from leaking secret config fields (starting with `hash_key`) in verbose audit payloads. The fix introduces a secret-field registry in `config.py` and ensures the audit path always uses the redacted variant of `to_dict()`, so no current or future secret field can reach an `on_audit` callback consumer.

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/config.py` | Add `_SECRET_FIELDS` frozenset; add `redact_secrets` kwarg to `to_dict()` |
| `petasos/premium/audit.py` | Call `to_dict(redact_secrets=True)` at L99 |
| `tests/test_config.py` | Add 4 tests for `_SECRET_FIELDS` and `to_dict(redact_secrets=…)` |
| `tests/test_audit.py` | Add 2 tests for verbose payload secret redaction |

### Files to leave alone

- `petasos/_types.py` — no changes needed; `AuditEvent` and `MappingProxyType` wrapping are correct as-is.
- `petasos/pipeline.py` — `Pipeline` does not call `to_dict()` directly; it passes `self._config` to `AuditEmitter`.
- `PetasosConfig.copy()` (L280–281) — calls `self.from_dict(self.to_dict())` with no `redact_secrets` flag, so secrets round-trip correctly. No change needed.
- `PetasosConfig.from_dict()` (L272–278) — consumes plain dicts; unaffected.

## Decisions

### Decision 1: Opt-in redaction, not always-on

`to_dict(redact_secrets=False)` (the default) returns the full config including secrets. Only the audit path explicitly passes `redact_secrets=True`. This preserves backward compatibility for serialization and `copy()`.

**Rationale:** `copy()` calls `self.from_dict(self.to_dict())` — if `to_dict()` always redacted, `copy()` would silently lose the real `hash_key` and break hash-mode anonymization. The brief explicitly calls this out.

### Decision 2: Sentinel `"[REDACTED]"`, not omission

Secret fields in the redacted dict are replaced with the string `"[REDACTED]"` when the value is not `None`, and left as `None` when it is `None`. The key is always present.

**Rationale:** Omitting the key would make it ambiguous whether `hash_key` was configured. The sentinel preserves presence information — a consumer can distinguish "configured but redacted" from "not configured."

### Decision 3: `_SECRET_FIELDS` as a frozenset constant

A module-level `frozenset[str]` named `_SECRET_FIELDS` in `petasos/config.py` is the single registry for secret field names. Adding a new secret field to `PetasosConfig` requires a one-line addition to `_SECRET_FIELDS`.

**Rationale:** Centralizes the secret registry. A test (`test_secret_fields_subset_of_config_fields`) verifies every name in `_SECRET_FIELDS` exists as a `PetasosConfig` dataclass field, catching typos and renames. The leading underscore is consistent with other module-internal symbols in `config.py` (e.g., `_validate_tier_thresholds`). `config.py` has no `__all__`; tests import `_SECRET_FIELDS` directly — no export change needed. (The brief suggests adding to `__all__`, but the "or keep it as a public-enough constant" clause applies.)

### Decision 4: No impact on `copy()`

`copy()` calls `self.from_dict(self.to_dict())` with the default `redact_secrets=False`. This means secrets round-trip correctly through `copy()`. No change to `copy()` is needed.

## Design

### 1. `_SECRET_FIELDS` constant (`petasos/config.py`)

Add at module level, after `_validate_tier_thresholds` (L22) to keep the tier-related constant cluster intact:

```python
_SECRET_FIELDS: frozenset[str] = frozenset({"hash_key"})
```

This is a `frozenset` so it cannot be mutated at runtime. Future secret fields (e.g., API keys, encryption keys) are added here.

### 2. `to_dict(redact_secrets=…)` (`petasos/config.py`, L261–270)

Replace the current `to_dict` with:

```python
def to_dict(self, *, redact_secrets: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {}
    for f in fields(self):
        val = getattr(self, f.name)
        if redact_secrets and f.name in _SECRET_FIELDS:
            d[f.name] = "[REDACTED]" if val is not None else None
            continue
        if isinstance(val, tuple):
            val = list(val)
        elif isinstance(val, MappingProxyType):
            val = dict(val)
        d[f.name] = val
    return d
```

The `redact_secrets` parameter is keyword-only to prevent accidental positional use. The `continue` after setting the redacted value skips the tuple/MappingProxyType conversion — `"[REDACTED]"` is always a plain string.

### 3. Audit payload change (`petasos/premium/audit.py`, L99)

Change line 99 from:

```python
data["config_snapshot"] = self._config.to_dict()
```

to:

```python
data["config_snapshot"] = self._config.to_dict(redact_secrets=True)
```

This is the only call site that needs the redacted variant. All other `to_dict()` callers (including `copy()`) continue using the default.

## Test plan

### New tests in `tests/test_config.py`

| Test | Asserts |
|------|---------|
| `test_to_dict_redact_secrets_masks_hash_key` | `to_dict(redact_secrets=True)` returns `"[REDACTED]"` for a non-None `hash_key` |
| `test_to_dict_redact_secrets_none_stays_none` | `to_dict(redact_secrets=True)` returns `None` when `hash_key=None` |
| `test_to_dict_default_preserves_hash_key` | `to_dict()` (no flag) still includes the raw `hash_key` value — backward compat regression guard |
| `test_secret_fields_subset_of_config_fields` | Every name in `_SECRET_FIELDS` is a valid field on `PetasosConfig` — catches typos and renames |

### New tests in `tests/test_audit.py`

| Test | Asserts |
|------|---------|
| `test_verbose_payload_redacts_hash_key` | Verbose audit payload's `config_snapshot["hash_key"]` is `"[REDACTED]"` |
| `test_verbose_payload_no_raw_secret_in_str` | The raw `hash_key` string does not appear anywhere in `str(payload)` — defense-in-depth against accidental leakage through nested serialization. Use a high-entropy fixture value (e.g., `'super-secret-hmac-key-for-test'`) to avoid false matches. |

### Existing tests

No existing tests need modification. The current `test_round_trip` in `TestConfigSerialization` calls `to_dict()` without `redact_secrets`, so it continues to pass unchanged. The audit tests use `_cfg()` with default `hash_key=None`, which is unaffected.

**Note on brief path divergence:** The brief references `tests/unit/test_config.py` and `tests/unit/premium/test_audit.py`. No `tests/unit/` directory exists; the actual test files are `tests/test_config.py` and `tests/test_audit.py`. This spec uses the actual paths.

## Test command

```
C:\Users\zioni\AppData\Local\Programs\Python\Python311\python.exe -m pytest tests/test_config.py tests/test_audit.py -v
```

## Done when

- [ ] `_SECRET_FIELDS` frozenset defined in `petasos/config.py`
- [ ] `to_dict(redact_secrets=True)` replaces secret values with `"[REDACTED]"`
- [ ] `_build_payload` calls `to_dict(redact_secrets=True)` for `config_snapshot`
- [ ] All 6 new tests pass
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of scope

- Audit payload encryption at rest (orthogonal — downstream concern)
- Redaction of PII in `ScanFinding` text within audit payloads (separate finding, different attack surface)
- `on_audit` callback sandboxing (callback trust is the integrator's responsibility)
- Drawbridge backport (Drawbridge doesn't have this surface)
- Feeding a redacted dict back through `from_dict()` — this would set `hash_key` to the literal sentinel `"[REDACTED]"`. This is caller error; `from_dict()` is not a deserialization target for audit payloads.
- Subclass secret fields — subclasses of `PetasosConfig` that add secret fields must override `to_dict` or extend the registry. `PetasosConfig` is a frozen dataclass not designed for subclassing.

## Deferred (P2+)

- **`_SECRET_FIELDS` completeness gap (edge-cases F-4).** The `test_secret_fields_subset_of_config_fields` test checks `_SECRET_FIELDS ⊆ config_fields` (no typos) but not the converse (no omissions). A future secret field added to `PetasosConfig` without updating `_SECRET_FIELDS` would leak. No automated enforcement is possible without a naming convention or annotation. Mitigate with a code-review checklist item: "Does this new field contain a secret? If so, add to `_SECRET_FIELDS`."
