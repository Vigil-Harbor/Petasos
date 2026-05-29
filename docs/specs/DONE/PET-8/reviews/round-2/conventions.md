# Conventions Review — PET-8 Round 2

## Closure of round 1 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | DEFAULT_TOOL_ALIASES mutable dict | CLOSED | spec: MappingProxyType used |
| F-2 | ToolCallGuard accesses pipeline._config | CLOSED | spec: config passed directly |
| F-3 | _premium_profile_hook missing double-gate | CLOSED | spec: _check_premium + suppress_rules check |
| F-4 | tier int vs str undocumented | CLOSED | spec: Decision documented |
| F-5 | Hyphenated vs underscored names | CLOSED | spec: Decision documented |
| F-6 | Premium gate not in flow | CLOSED | spec: Step 0 added |
| F-7 | _build_premium_features string check | CLOSED | spec: uses `is not None` |
| F-8 | TierThresholds duplicates validation | CLOSED | spec: shared helper proposed |
| F-9 | tool_alias_map premature | CLOSED | Brief-authorized |
| F-10 | confidence_floor contradicts brief | CLOSED | spec: Decision documented |
| F-11 | GuardResult.to_dict() missing | CLOSED | spec: included in definition |

## Findings

### F-1: ToolCallGuard accesses `pipeline._check_premium()` — private method
**Severity:** P2
**Where:** spec step 0
**Convention violated:** Encapsulation pattern established by round 1 fix for config access. PET-7 designed `_check_premium` as pipeline-internal.
**Fix:** Add public `Pipeline.is_premium_active` property or `Pipeline.check_premium(feature)` method.

### F-2: `_validate_tier_thresholds` hardcodes 30.0 instead of using canonical constant
**Severity:** P3
**Where:** spec § D1 shared helper
**Convention violated:** Single source of truth. Codebase has `_TIER3_FLOOR` in config.py and `TIER3_FLOOR` in escalation.py.
**Fix:** Specify that helper imports `TIER3_FLOOR` from `petasos.premium.escalation`.

### F-3: `DEFAULT_FREQUENCY_WEIGHTS` in existing code is plain dict (precedent note)
**Severity:** P4
**Note:** Not a PET-8 defect. Existing tech debt. PET-8 correctly uses MappingProxyType for its new constant.

### F-4: CLAUDE.md Target Layout shows `profiles.py` but spec creates `profiles/` package
**Severity:** P3
**Convention violated:** CLAUDE.md maintenance (wiki/filemap update after work).
**Fix:** Add CLAUDE.md to "Files to modify" table or add "Done when" criterion for updating Target Layout.

### F-5: `Pipeline.config` property is a silent addition beyond brief
**Severity:** P3
**Note:** Category (c) — acceptable spec-level addition with clear rationale (supports guard encapsulation fix). No action needed.

STATUS: GREEN
