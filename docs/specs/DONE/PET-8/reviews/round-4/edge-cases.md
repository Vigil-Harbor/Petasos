# Edge-Cases Review — PET-8 Round 4

## Closure of round 3 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | with_suppress_rules() allocation under sustained traffic | CLOSED | P3, no change needed; implementers MAY cache |
| F-2 | _resolve_profile with empty string profile_name | CLOSED | spec: truthy check (`if self._config.profile_name:`) |
| F-3 | _validate_tier_thresholds import creates fragile dependency inversion | CLOSED | spec: TIER3_FLOOR canonical in config.py; escalation.py imports from config |
| F-4 | tier_thresholds override dict with partial keys | CLOSED | spec: "must provide all three keys; missing keys raise ValueError" |
| F-5 | Tier derivation uses pre-inspection state | CLOSED | P3, correct behavior — ordering rationale implicit |
| F-6 | with_suppress_rules() doesn't preserve subclass | CLOSED | P4, MinimalScanner not documented as subclassable |
| F-7 | tool_alias_map with empty-string value | CLOSED | spec: "empty-string values raise ValueError at load time" |
| F-8 | importlib.resources encoding on Windows | CLOSED | spec: "read_text(encoding='utf-8')" |

## Findings

### F-1: Profile override merge with nested dict (suppress_rules within profile)
**Severity:** P2
**Where:** spec § D3, profile override merge semantics
**Issue:** Custom profile with `suppress_rules: ["rule_a"]` — merge semantics say "replace" for lists. If a user provides a partial suppress_rules list intending to *add* to the base, they'll accidentally replace. Documented behavior is correct (replace), but could surprise users.
**Fix:** P2 — no spec change needed. Document in implementation that list merge is replacement, not union. Optionally add a `suppress_rules_add` field in a future version.

### F-2: concurrent guard.evaluate() calls share FrequencyTracker state
**Severity:** P3
**Where:** spec § D2 evaluation flow step 2
**Issue:** Two concurrent evaluate() calls on the same session_id both read tier from FrequencyTracker. If first call triggers a frequency update (step 5), second call's tier derivation may be stale by microseconds.
**Fix:** P3 — acceptable race. Tier re-derivation happens at start of each call; next call will reflect the update. No lock needed.

### F-3: tool_params with circular references
**Severity:** P3
**Where:** spec § step 5, json.dumps fallback
**Issue:** `json.dumps(value)` raises ValueError on circular refs before TypeError. The spec's try/except catches TypeError but not ValueError for this case.
**Fix:** P3 — circular refs in tool params are exotic. str(value) would hit recursion limit. Implementer may catch (TypeError, ValueError) if desired.

### F-4: Profile with confidence_floor = 0.0 suppresses all findings
**Severity:** P3
**Where:** spec § step 5b confidence floor
**Issue:** `confidence_floor = 0.0` with strict less-than means `finding.confidence < 0.0` — effectively suppresses nothing (confidence is never negative). This is correct! But `confidence_floor = 0.0` might mislead users who expect it to mean "suppress everything."
**Fix:** P3 — correct behavior. Optionally validate confidence_floor > 0.0 at load time to prevent confusion.

### F-5: Deeply nested tool_params exceeding json.dumps default recursion
**Severity:** P3
**Where:** spec § step 5, parameter content scanning
**Issue:** Very deep nesting in tool_params could cause json.dumps to hit Python's default recursion limit (1000) before the str() fallback kicks in, raising RecursionError not TypeError.
**Fix:** P3 — edge case. Implementer may add RecursionError to the except clause.

### F-6: FrequencyTracker.get_session_state returns None for unknown session_id
**Severity:** P4
**Note:** Spec step 2 derives tier from FrequencyTracker. If session_id is unknown (no prior scans), PET-7's FrequencyTracker returns a fresh SessionState at tier 0 / Tier 1. No edge case — by design.

STATUS: GREEN
