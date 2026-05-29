# Edge-Cases Review — PET-8 Round 2

## Closure of round 1 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | Empty tool_params scanned | CLOSED | spec step 5a: short-circuit for empty dict |
| F-2 | None values in tool_params | CLOSED | spec step 5b: skip None entries |
| F-3 | Namespace stripping leaves empty string | CLOSED | spec step 1e: postcondition blocks empty name |
| F-4 | Pipeline error during param scanning | CLOSED | spec step 5e: errors+no findings → param_scan_unsafe=False |
| F-5 | Premium gate missing | CLOSED | spec step 0: premium gate added |
| F-6 | Race condition on register() | CLOSED | documented as startup-only |
| F-7 | Malformed JSON at construction | CLOSED | documented as programming errors |
| F-8 | Large tool_params | PARTIAL | No size pre-check; pipeline's max_payload_bytes handles it. P3. |
| F-9 | confidence_floor ordering | CLOSED | explicit stage ordering 5b/5c before _compute_safe |
| F-10 | evaluate_tier private access | CLOSED | config passed directly + profile thresholds inline |
| F-11 | tier int vs str | CLOSED | decision documented |
| F-12 | Hook callsite not shown | CLOSED | modified flow with stage numbering |
| F-13 | Alias map order | CLOSED | explicit merge semantics |
| F-14 | NaN confidence | PARTIAL | Not addressed; P3 acceptable |

## Findings

### F-1: Step 5e does not document partial-failure scenario (errors + findings)
**Severity:** P3
**Where:** spec step 5e
**Issue:** When pipeline returns both errors AND findings (partial failure), the else-branch silently uses partial results. Correct behavior but undocumented.
**Fix:** Add note: "In partial-failure scenarios (errors present but findings also present), findings from successful scanners are used."

### F-2: tool_params serialization crashes on non-JSON-serializable values
**Severity:** P1
**Where:** spec step 5b ("Otherwise: json.dumps(value)")
**Issue:** Values like functions, bytes, datetime, or custom objects raise `TypeError` from `json.dumps()`. No exception handling specified. ToolCallGuard is not governed by "pipeline never throws" but an unhandled error in a pre_tool_call hook could crash the Hermes integration.
**Fix:** Wrap json.dumps in try/except TypeError: use `str(value)` as fallback. Or document that callers must ensure JSON-serializable params and add a precondition.

### F-3: ToolCallGuard step 0 accesses pipeline._check_premium — private method
**Severity:** P2
**Where:** spec step 0
**Issue:** Same as correctness F-1. Structural encapsulation concern.
**Fix:** Public method or pass premium_active to constructor.

### F-4: Confidence floor comparison operator ambiguous
**Severity:** P2
**Where:** spec Stage 5b
**Issue:** "Drop findings below this confidence" — does "below" mean `<` (strict) or `<=`? With floor=0.0, `<=` would incorrectly drop zero-confidence findings under the general profile.
**Fix:** Explicitly state: "Drop findings where `finding.confidence < profile.confidence_floor` (strict less-than)."

### F-5: Profile tier_thresholds — NaN/inf scores silently produce tier="none"
**Severity:** P3
**Where:** spec step 2 inline tier derivation
**Issue:** NaN score passes all `>=` as False → tier="none" (fail-open). This is safe behavior but undocumented.
**Fix:** No code change needed. Optional note that NaN/inf scores default to tier="none".

### F-6: MinimalScanner structural rules silently filtered from profile suppress_rules
**Severity:** P3
**Where:** spec _premium_profile_hook
**Issue:** Profile suppress_rules containing structural rule IDs are silently ignored by MinimalScanner constructor. Correct defensive behavior but undocumented.
**Fix:** Optional note: "Structural rules cannot be suppressed even via profiles — MinimalScanner enforces this."

### F-7: Empty session_id string silently accepted
**Severity:** P2
**Where:** spec evaluate() parameter
**Issue:** `session_id=""` is valid str but likely a caller bug. Guard treats it as "no session" (tier=none). No validation.
**Fix:** Document that empty session_id yields tier=none, or validate non-empty with early return.

### F-8: Dict merge for custom profiles — unknown keys and type mismatches unspecified
**Severity:** P2
**Where:** spec resolution logic (dict merge)
**Issue:** What happens with unknown keys in override dict? What about wrong value types? The merge semantics section covers known fields only.
**Fix:** Specify: "Unknown keys silently ignored. Type mismatches raise ValueError."

### F-9: All tool_params values are None — correctly handled
**Severity:** N/A (verified correct)
**Note:** Step 5c catches the post-filtering empty case. No issue.

### F-10: Profile tool_exempt_list entries may not be normalized
**Severity:** P2
**Where:** spec step 4 (exempt check)
**Issue:** Exempt list loaded from JSON as-is but compared against normalized tool name. `"Read"` in exempt list won't match normalized `"read"`. Entries with namespace prefixes or mixed case silently fail.
**Fix:** Specify that tool_exempt_list entries are normalized (lower-cased) at profile load time.

### F-11: _premium_profile_hook accesses MinimalScanner private attributes
**Severity:** P2
**Where:** spec line 383-385
**Issue:** `self._minimal_scanner._max_payload_bytes` etc. Couples hook to scanner internals.
**Fix:** Add public properties to MinimalScanner or a `with_suppress_rules()` factory method.

STATUS: RED P0=0 P1=1 P2=6 P3=3
