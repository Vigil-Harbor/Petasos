# Correctness Review — PET-8 Round 2

## Closure of round 1 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | importlib.resources naming conflict | CLOSED | spec § Decisions "Profile package structure": profiles/ is package with `__init__.py` |
| F-2 | Profile tier_thresholds no integration into ToolCallGuard | CLOSED | spec § D2 step 2: inline comparison when profile thresholds available |
| F-3 | _premium_profile_hook placement ambiguity | CLOSED | spec § D3 modified flow with explicit stage numbering (1b before 2) |
| F-4 | GuardResult.to_dict() missing from definition | CLOSED | spec shows to_dict() in dataclass definition |
| F-5 | _build_premium_features profiles gate too narrow | CLOSED | spec: `self._default_profile is not None` |
| F-6 | ToolCallGuard accesses private _config | CLOSED | spec: config passed directly to constructor |
| F-7 | SessionState not exported | CLOSED | spec Deferred section acknowledges as acceptable |
| F-8 | Plane ticket not cached | PARTIAL | P3, informational |

## Findings

### F-1: ToolCallGuard accesses private `_check_premium()` on Pipeline
**Severity:** P2
**Where:** spec § D2 evaluation flow step 0
**Issue:** `self._pipeline._check_premium("tool_guard")` accesses a private method. The spec's own Decisions section states "It does not reach into `pipeline._config`" but does reach into `_check_premium`. FrequencyTracker (the pattern referenced) does not call back into Pipeline at all.
**Fix:** Either expose as public `Pipeline.check_premium()` method, pass a `premium_active` getter to constructor, or document as acceptable private-method access.

### F-2: `_validate_tier_thresholds` omits finiteness check
**Severity:** P3
**Where:** spec § D1 (shared helper)
**Issue:** `PetasosConfig.__post_init__` validates `math.isfinite()` but the spec's shared helper only validates ascending + floor.
**Fix:** Add finite check to the helper.

### F-3: Plane ticket not cached in MCP memory
**Severity:** P3
**Fix:** Cache ticket for future review passes.

### F-4: Stages 5b/5c not explicitly gated behind premium check
**Severity:** P2
**Where:** spec § D3 modified flow
**Issue:** The profile hook (Stage 1b) gates on `_check_premium("profiles")` but Stages 5b (confidence floor) and 5c (severity overrides) don't show their own premium gate. If profile is provided but premium inactive, behavior is ambiguous.
**Fix:** Add note: "Stages 5b/5c are no-ops when `_check_premium('profiles')` is False OR active_profile is None."

### F-5: `_resolve_profile` helper referenced but never defined
**Severity:** P2
**Where:** spec § D3 Pipeline.__init__
**Issue:** `self._default_profile = self._resolve_profile(profile)` references an undefined method. Logic is described in prose but no code block shows signature, error handling, or config.profile_name fallback path.
**Fix:** Add code block for `_resolve_profile()` or inline the resolution logic in the `__init__` description.

STATUS: GREEN
