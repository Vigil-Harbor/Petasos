# Edge-Cases Review — round 1

## Closure of round 0 findings
N/A — round 1

## Findings

### F-1: Empty-string `hash_key` treated as "configured but redacted" — misleading sentinel
**Severity:** P3
**Where:** spec Design §2 (the `to_dict` redaction logic)
**Detail:** `hash_key=""` passes the `val is not None` check and gets `"[REDACTED]"`. Semantically misleading but not a leak — empty string itself carries no secret value.
**Suggested fix:** Document as conscious choice: empty-string handling is a validation concern, not a redaction concern.

### F-2: `from_dict` on a redacted dict silently poisons config
**Severity:** P2
**Where:** spec "Files to leave alone" section — `from_dict` declared unaffected
**Detail:** `from_dict({"hash_key": "[REDACTED]", ...})` succeeds and creates a config with literal `"[REDACTED]"` as the HMAC key. Silent data corruption if used for hash-mode anonymization.
**Suggested fix:** Document the hazard in Out of Scope: feeding redacted dicts back through `from_dict()` is caller error.

### F-3: Test file paths diverge between brief and spec
**Severity:** P2
**Where:** Brief references `tests/unit/test_config.py` and `tests/unit/premium/test_audit.py`; spec uses `tests/test_config.py` and `tests/test_audit.py`
**Detail:** Spec is correct for the actual repo layout. Brief's paths don't exist.
**Suggested fix:** Acknowledge the correction from the brief's suggested paths.

### F-4: No test for `_SECRET_FIELDS` completeness against future additions
**Severity:** P2
**Where:** spec test plan — `test_secret_fields_subset_of_config_fields`
**Detail:** Test checks `_SECRET_FIELDS ⊆ config_fields` (no typos), not `secret_fields ⊆ _SECRET_FIELDS` (no omissions). A new secret field added to PetasosConfig without updating `_SECRET_FIELDS` would leak.
**Suggested fix:** Acknowledge gap; recommend code-review checklist or comment convention.

### F-5: `str(payload)` test may not catch all leakage vectors
**Severity:** P3
**Where:** spec test plan — `test_verbose_payload_no_raw_secret_in_str`
**Detail:** Test depends on fixture using a sufficiently unique hash_key value.
**Suggested fix:** Specify a high-entropy fixture value (e.g., `'super-secret-hmac-key-for-test'`).

### F-6: Subclass fields not covered by `_SECRET_FIELDS`
**Severity:** P3
**Where:** spec Design §1
**Detail:** Subclasses of frozen `PetasosConfig` could add secret fields not in `_SECRET_FIELDS`. Unlikely given frozen dataclass design.
**Suggested fix:** Add to Out of Scope.

### F-7: Concurrency is a non-issue (P4, informational)
### F-8: MappingProxyType wrapping is correct (P4, informational)
### F-9: Line numbers may drift (P4, informational)

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 3 | P4: 3

STATUS: GREEN
