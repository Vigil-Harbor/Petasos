# Edge-Cases Review — PET-8 Round 1

## Findings

### F-1: Empty tool_params produces empty string for param scanning
**Severity:** P2
**Issue:** Empty dict → empty string → full pipeline scan on "". Should short-circuit.
**Fix:** Add short-circuit: if tool_params empty or param_text whitespace-only, skip inspect().

### F-2: tool_params with None values — str(None) = "None" scanned
**Severity:** P2
**Issue:** Spec conflates `str(v)` and `json.dumps` for serialization. None → "None" string scanned.
**Fix:** Clarify serialization strategy. Skip None values or use json.dumps consistently.

### F-3: Namespace stripping matches entire tool name, leaving empty string
**Severity:** P1
**Issue:** `tool_name = "hermes__"` → strip → empty string. No postcondition on empty result.
**Fix:** Add postcondition: if normalized_name empty after transformations, block with "invalid tool name".

### F-4: pipeline.inspect() error during param scanning not fully specified
**Severity:** P1
**Issue:** Pipeline returns safe=False on error (not actual findings). Guard interprets safe=False as param_scan_unsafe=True. Doesn't distinguish "scan failed" from "content unsafe".
**Fix:** Check result.errors non-empty + findings empty → treat as param_scan_unsafe=False.

### F-5: ToolCallGuard behavior when premium deactivated — no step 0 gate
**Severity:** P1
**Issue:** Test #28 expects pass-through when premium inactive but evaluation flow has no premium gate step. Deactivating premium at tier3 silently removes protection.
**Fix:** Add step 0: if not premium active, return allowed=True. Document fail-open is deliberate for unlicensed deployments.

### F-6: Race condition on ProfileResolver._profiles with register()
**Severity:** P2
**Issue:** register() mutates dict after construction. Thread safety claim only covers per-call copies.
**Fix:** Document register() is startup-only, not safe for concurrent access.

### F-7: Malformed profile JSON raises during Pipeline construction
**Severity:** P2
**Issue:** Raises in __init__, potentially violating "pipeline never throws" interpretation.
**Fix:** Document: validation errors at construction are programming errors, not runtime. Consistent with __post_init__ pattern.

### F-8: Extremely large tool_params
**Severity:** P2
**Issue:** 10MB param string runs full pipeline before oversized-payload check fires. Suboptimal latency.
**Fix:** Optional fast-path: check concatenated size before inspect().

### F-9: confidence_floor interaction with safe determination ordering
**Severity:** P1
**Issue:** Spec says filtering runs "after merge_findings, before premium hooks" but _compute_safe() runs at stage 8 (after hooks). If filter modifies merged before _compute_safe(), safe reflects filtered findings. Ordering unclear.
**Fix:** State explicitly: confidence floor + severity overrides applied between stage 5 and stage 6. Filtered merged used for ALL subsequent stages including _compute_safe().

### F-10: evaluate_tier() in guard uses pipeline._config — private access + no profile thresholds
**Severity:** P2
(Overlaps with correctness F-2 and F-6)

### F-11: GuardResult.tier is str in spec but int in brief
**Severity:** P2
**Issue:** Brief says int, spec says str. Spec is correct (matches evaluate_tier return type).

### F-12: _premium_profile_hook returns MinimalScanner but callsite not shown
**Severity:** P2
(Overlaps with correctness F-3)

### F-13: tool_alias_map application order ambiguous
**Severity:** P3

### F-14: NaN confidence values silently dropped by floor filter
**Severity:** P3

STATUS: RED P0=0 P1=4 P2=6 P3=2
