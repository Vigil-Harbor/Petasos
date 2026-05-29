# Correctness Review — PET-8 Round 1

## Findings

### F-1: File/module naming conflict with importlib.resources resolution
**Severity:** P1
**Where:** spec § D1 Files to create + § D1 ProfileResolver loading
**Issue:** Spec creates both `petasos/premium/profiles.py` (module) and `petasos/premium/profiles/*.json` (directory). `importlib.resources.files("petasos.premium.profiles")` resolves to the MODULE, not the directory.
**Fix:** Use `importlib.resources.files("petasos.premium") / "profiles"` to traverse from parent package, or restructure (profiles/ as package with __init__.py).

### F-2: Profile tier_thresholds have no integration path into ToolCallGuard tier derivation
**Severity:** P1
**Where:** spec § D2 evaluation flow step 2
**Issue:** `evaluate_tier(state.last_score, pipeline._config)` always uses pipeline config thresholds. Profile's `tier_thresholds` overrides are never bridged into this call.
**Fix:** ToolCallGuard must construct modified config or pass thresholds directly when profile has non-None tier_thresholds.

### F-3: _premium_profile_hook placement ambiguity
**Severity:** P1
**Where:** spec § D3 Pipeline integration
**Issue:** "Runs after normalization, before scanner fan-out" is ambiguous — MinimalScanner (step 2) runs before ML fan-out (step 4). Hook must run before step 2 for suppress_rules to take effect. Modified _inspect_inner flow not shown.
**Fix:** Specify "before syntactic pre-filter" and show the modified _inspect_inner callsite.

### F-4: GuardResult.to_dict() in test plan but missing from dataclass definition
**Severity:** P2

### F-5: _build_premium_features() profiles gate too narrow
**Severity:** P2
**Issue:** Gates on `self._config.profile_name is not None` but profiles can be passed directly as ResolvedProfile or per-call dict. Gate should check `self._default_profile is not None`.

### F-6: ToolCallGuard accesses Pipeline's private _config attribute
**Severity:** P2
**Issue:** `_config` is private. Should expose via public property or pass config to guard constructor.

### F-7: SessionState not exported from premium/__init__.py
**Severity:** P2
**Issue:** Guard uses `frequency_tracker.get_state()` which returns `SessionState | None` but type not re-exported.

### F-8: Plane ticket not cached in MCP memory
**Severity:** P3

STATUS: RED P0=0 P1=3 P2=4 P3=1
