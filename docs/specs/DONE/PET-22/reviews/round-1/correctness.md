# Correctness Review — round 1

## Closure of round 0 findings
N/A — round 1

## Findings

No findings.

Every claim the spec makes about the current code has been verified against the actual source files:

**Line numbers verified:**
- `to_dict()` at `petasos/config.py` L261-270 — confirmed
- `from_dict()` at `petasos/config.py` L272-278 — confirmed
- `copy()` at `petasos/config.py` L280-281 — confirmed
- `_build_payload` at `petasos/premium/audit.py` L66-104 — confirmed
- `config_snapshot` assignment at `petasos/premium/audit.py` L99 — confirmed
- `TIER3_FLOOR` constant at `petasos/config.py` L13 — confirmed (placement target for `_SECRET_FIELDS`)

**Call-site completeness verified:**
- Only two production callers of `PetasosConfig.to_dict()`: `copy()` (L281) and `_build_payload` (L99). The spec correctly identifies both and correctly notes only L99 needs the redacted variant.
- `pipeline.py` does not call `to_dict()` — confirmed via grep; it passes `self._config` to `AuditEmitter`.

**Code block consistency:**
- The proposed `to_dict` replacement correctly extends the existing logic by adding the `redact_secrets` parameter and the `_SECRET_FIELDS` check, while preserving the existing tuple/MappingProxyType conversion.
- The audit change is a one-line replacement at exactly L99 of audit.py.

**Done-when coverage:**
- All 6 brief "Done When" criteria are mapped to spec sections.
- All 6 brief-required tests are present in the spec.

**Brief decisions carried forward:**
- Opt-in redaction (not always-on) — spec Decision 1
- Sentinel `"[REDACTED]"` (not omission) — spec Decision 2
- `_SECRET_FIELDS` as frozenset — spec Decision 3
- No impact on `copy()` — spec Decision 4

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 0 | P4: 0

STATUS: GREEN
