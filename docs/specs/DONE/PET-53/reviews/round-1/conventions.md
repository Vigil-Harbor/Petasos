# Conventions Review -- round 1

## Findings

### F-1: Pipeline accesses private attributes of audit/alerting subsystems
**Severity:** P2
`self._audit_emitter._last_callback_error` and `self._alert_manager._callback_errors` — pipeline reads private `_`-prefixed attributes.

### F-2: Error string format inconsistency between callback-level and hook-level errors
**Severity:** P3
PET-48 uses `f"{type(exc).__name__}: {exc}"`. Spec uses `f"on_audit callback: {exc}"` (no type name). Important for empty `str()` on BaseException subclasses.

### F-3: Pipeline hook return type changes from None — silent spec addition
**Severity:** P3
Brief says "add a comment documenting defense-in-depth"; spec changes return types. Surfacing as category (c) addition with rationale in D2.

### F-4: `_last_callback_error` clearing placement inconsistency
**Severity:** P3
D2 says "cleared at the top" but Section 2 code clears before callback block. Inconsistent with alerting pattern.

### F-5: Dead `_NONE_SENTINEL` in alerting.py
**Severity:** P4
alerting.py L30 defines `_NONE_SENTINEL` but never uses it. Spec already modifies alerting.py.

### F-6: Filemap description stale after PET-53
**Severity:** P4
Post-merge wiki task, not a spec defect.

### F-7: Test plan references conftest fixture that doesn't exist
**Severity:** P4
Same as correctness F-6.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 3 | P4: 3

STATUS: GREEN
