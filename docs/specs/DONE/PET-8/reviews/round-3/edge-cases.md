# Edge-Cases Review — PET-8 Round 3

## Closure of round 2 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | Step 5e partial-failure | CLOSED | P3, correct behavior via if/else |
| F-2 | json.dumps TypeError | CLOSED | spec: try/except with str() fallback |
| F-3 | _check_premium private | CLOSED | spec: is_premium_active() public method |
| F-4 | Confidence floor ambiguous | CLOSED | spec: "strict less-than" |
| F-5 | NaN/inf scores | CLOSED | P3, safe behavior |
| F-6 | Structural rules filtered | CLOSED | P3, MinimalScanner enforces |
| F-7 | Empty session_id | CLOSED | spec: Deferred section documents |
| F-8 | Dict merge unknown keys | CLOSED | spec: semantics specified |
| F-9 | All params None | CLOSED | step 5c handles |
| F-10 | tool_exempt_list normalization | CLOSED | spec: normalized at load time |
| F-11 | MinimalScanner private access | CLOSED | spec: with_suppress_rules() factory |

## Findings

### F-1: with_suppress_rules() allocation under sustained traffic
**Severity:** P3
**Where:** spec line 422, 445
**Issue:** Each inspect() call with active profile creates new MinimalScanner instance. No caching specified.
**Fix:** P3 — no change needed. Optionally note implementers MAY cache by suppress_rules frozenset.

### F-2: _resolve_profile with empty string profile_name
**Severity:** P2
**Where:** spec line 339-340
**Issue:** `PetasosConfig(profile_name="")` passes `is not None` check, calls `resolve("")`, raises KeyError.
**Fix:** Use truthy check (`if self._config.profile_name:`) or validate non-empty in PetasosConfig.

### F-3: _validate_tier_thresholds import creates fragile dependency inversion
**Severity:** P1
**Where:** spec lines 77-88
**Issue:** config.py importing from petasos.premium.escalation inverts the architecture (premium → config is the normal direction). While no circular import exists today, adding any runtime import to escalation.py would create one. Import ordering becomes fragile.
**Fix:** Keep TIER3_FLOOR canonical in config.py. Have escalation.py import it. Helper stays in config.py without external import.

### F-4: tier_thresholds override dict with partial keys (missing tier3)
**Severity:** P2
**Where:** spec line 131
**Issue:** Override dict with `{"tier_thresholds": {"tier1": 10, "tier2": 25}}` — missing tier3 undefined.
**Fix:** Add: tier_thresholds override must provide all three keys; missing keys raise ValueError.

### F-5: Tier derivation uses pre-inspection state
**Severity:** P3
**Where:** spec step 2
**Issue:** Param scanning updates frequency scores but tier was derived before scanning. Correct behavior but rationale implicit.
**Fix:** P3 — optionally document ordering rationale.

### F-6: with_suppress_rules() doesn't preserve subclass
**Severity:** P4
**Note:** MinimalScanner not documented as subclassable. Nit.

### F-7: tool_alias_map with empty-string value blocks tool misleadingly
**Severity:** P2
**Where:** spec step 1c + 1e
**Issue:** Alias `{"tool": ""}` maps to empty string, blocked by postcondition with generic error.
**Fix:** Validate alias map values at profile load time — no empty-string values allowed.

### F-8: importlib.resources encoding on Windows wheel install
**Severity:** P3
**Where:** spec line 116
**Issue:** JSON loading should specify encoding="utf-8" for cross-platform consistency.
**Fix:** Add note: "JSON loaded via traversable.read_text(encoding='utf-8')".

STATUS: RED P0=0 P1=1 P2=3 P3=3 P4=1
