# Correctness Review — PET-8 Round 3

## Closure of round 2 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | _check_premium private access | CLOSED | spec: Pipeline.is_premium_active() public method added; guard step 0 uses it |
| F-2 | _validate_tier_thresholds omits finiteness | CLOSED | spec: math.isfinite() check added |
| F-3 | Plane ticket not cached | PARTIAL | P3, informational |
| F-4 | Stages 5b/5c not premium-gated | CLOSED | spec: explicit gate documented |
| F-5 | _resolve_profile undefined | CLOSED | spec: full code block added |

## Findings

### F-1: _validate_tier_thresholds in config.py creates import from base to premium
**Severity:** P2
**Where:** spec lines 77-88
**Issue:** `config.py` currently has zero runtime imports from `premium/`. Adding `from petasos.premium.escalation import TIER3_FLOOR` inverts the dependency direction. No circular import at runtime (escalation uses TYPE_CHECKING for config import), but fragile layering.
**Fix:** Document as deliberate trade-off, OR move canonical constant to config.py and have escalation.py import from there.

### F-2: Plane ticket not cached
**Severity:** P3
**Fix:** Informational, carried forward.

STATUS: GREEN
