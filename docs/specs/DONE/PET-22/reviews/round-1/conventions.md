# Conventions Review — round 1

## Closure of round 0 findings
N/A — round 1

## Findings

### F-1: Brief references `tests/unit/` paths that do not exist; spec correctly fixes them
**Severity:** P3 (informational)
**Detail:** Spec uses `tests/test_config.py` and `tests/test_audit.py` which match the actual layout.

### F-2: Brief proposes adding `_SECRET_FIELDS` to `__all__`; spec silently drops this
**Severity:** P4
**Detail:** `config.py` has no `__all__`; underscore prefix is consistent with `_validate_tier_thresholds`.

### F-3: `_SECRET_FIELDS` underscore prefix vs `TIER3_FLOOR` public constant naming
**Severity:** P3
**Detail:** Two-tier pattern exists in config.py: public (`TIER3_FLOOR`) without underscore, internal (`_validate_tier_thresholds`) with underscore. Both choices defensible; brief uses underscore.

### F-4: Spec `to_dict` code skips conversion for secret fields — correct behavior
**Severity:** P4 (informational)

### F-5: Brief's `__all__` directive silently dropped — qualifies as category-d silent removal
**Severity:** P2
**Detail:** Brief explicitly directs adding to `__all__`. Spec drops this without rationale. Should acknowledge the divergence.
**Suggested fix:** Add rationale note in Decision 3.

### F-6: Import pattern precedent undocumented (P4, informational)
### F-7: `_SECRET_FIELDS` placement nit — consider after `_validate_tier_thresholds` (P4)

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 2 | P4: 4

STATUS: GREEN
