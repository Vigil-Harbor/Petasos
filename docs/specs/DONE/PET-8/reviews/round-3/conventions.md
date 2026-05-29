# Conventions Review — PET-8 Round 3

## Closure of round 2 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | _check_premium private access | CLOSED | spec: Pipeline.is_premium_active() |
| F-2 | _validate_tier_thresholds hardcodes 30.0 | CLOSED | spec: imports TIER3_FLOOR |
| F-3 | DEFAULT_FREQUENCY_WEIGHTS plain dict | N/A | P4, existing tech debt |
| F-4 | CLAUDE.md Target Layout | CLOSED | spec: in Files to modify |
| F-5 | Pipeline.config silent addition | N/A | Accepted |

## Findings

### F-1: _validate_tier_thresholds inverts dependency direction (config → premium)
**Severity:** P3
**Where:** spec lines 77-88
**Issue:** config.py has zero premium imports today. Adding one inverts the dependency direction.
**Fix:** Move canonical TIER3_FLOOR to config.py; have escalation.py import from there.

### F-2: Spec doesn't specify removal of _TIER3_FLOOR from config.py
**Severity:** P3
**Where:** config.py:13
**Issue:** After refactoring to shared helper, `_TIER3_FLOOR` becomes dead code if not cleaned up.
**Fix:** Add to "Files to modify": remove `_TIER3_FLOOR` constant.

### F-3: with_suppress_rules() establishes new copy pattern
**Severity:** P4
**Note:** `with_*` pattern is idiomatic Python for non-dataclass immutable copy. No convention violation.

### F-4: tool_exempt_list normalization documented in wrong section
**Severity:** P4
**Note:** Documented in profile table section, not ProfileResolver definition. Minor readability nit.

STATUS: GREEN
