# Conventions Review — PET-8 Round 1

## Findings

### F-1: DEFAULT_TOOL_ALIASES declared as mutable dict violates Frozen Exports invariant
**Severity:** P2
**Fix:** Use MappingProxyType[str, str].

### F-2: ToolCallGuard accesses pipeline._config (private attribute)
**Severity:** P2
**Fix:** Pass config to constructor (like FrequencyTracker pattern) or expose public property.

### F-3: _premium_profile_hook missing double-gate pattern
**Severity:** P2
**Fix:** Add config toggle check after _check_premium(), matching PET-7 pattern.

### F-4: Brief says tier: int, spec says tier: str — undocumented divergence
**Severity:** P3
**Fix:** Add note to Decisions section acknowledging change and rationale.

### F-5: Hyphenated vs underscored profile names — properly documented
**Severity:** P4

### F-6: ToolCallGuard premium gate not shown in evaluation flow
**Severity:** P2
**Fix:** Add step 0 to evaluation flow per PET-7 pattern.

### F-7: _build_premium_features() uses string non-None check instead of bool toggle
**Severity:** P3

### F-8: TierThresholds duplicates PetasosConfig validation
**Severity:** P3
**Fix:** Extract shared validation function or document duplication rationale.

### F-9: tool_alias_map premature for N=1 callsite
**Severity:** P3
**Note:** Authorized by brief, acceptable.

### F-10: confidence_floor filtering location contradicts brief's "before scanner fan-out"
**Severity:** P3
**Fix:** Acknowledge in Decisions that this is post-merge, not pre-fan-out.

### F-11: GuardResult.to_dict() in test but not in definition
**Severity:** P4

STATUS: GREEN
