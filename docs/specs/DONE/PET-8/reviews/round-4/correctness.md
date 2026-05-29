# Correctness Review — PET-8 Round 4

## Closure of round 3 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | _validate_tier_thresholds import from base to premium | CLOSED | spec: TIER3_FLOOR canonical in config.py; escalation.py imports from config |
| F-2 | Plane ticket not cached | CLOSED | P3 informational, carried across rounds — no spec change needed |

## Findings

### F-1: _resolve_profile KeyError message unhelpful
**Severity:** P3
**Where:** spec § _resolve_profile code block
**Issue:** When profile_name is truthy but not found, KeyError message shows only the name without listing available profiles.
**Fix:** Optionally note: raise KeyError(f"Unknown profile '{name}'. Available: {list(self._profiles.keys())}").

### F-2: GuardResult.to_dict() includes param_scan_result serialization
**Severity:** P4
**Note:** Spec defines to_dict() but doesn't specify whether param_scan_result (a PipelineResult) is serialized recursively or summarized. Minor — implementer judgment.

STATUS: GREEN
