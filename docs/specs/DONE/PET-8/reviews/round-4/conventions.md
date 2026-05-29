# Conventions Review — PET-8 Round 4

## Closure of round 3 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | _validate_tier_thresholds inverts dependency direction | CLOSED | spec: TIER3_FLOOR canonical in config.py; escalation.py imports from there |
| F-2 | Spec doesn't specify removal of _TIER3_FLOOR from config.py | CLOSED | spec: escalation.py in "Files to modify" — implementation removes dead constant |
| F-3 | with_suppress_rules() establishes new copy pattern | CLOSED | P4, idiomatic Python |
| F-4 | tool_exempt_list normalization documented in wrong section | CLOSED | P4, minor readability nit |

## Findings

### F-1: petasos/scanners/*.py glob in "Files to leave alone" contradicts minimal.py in "Files to modify"
**Severity:** P2
**Where:** spec § Scope
**Issue:** "Files to leave alone" lists `petasos/scanners/*.py` but "Files to modify" lists `petasos/scanners/minimal.py` (for with_suppress_rules()). The glob includes minimal.py.
**Fix:** Amend "Files to leave alone" to `petasos/scanners/{llm_guard,llama_firewall,presidio}.py` (explicit list excluding minimal.py), or add "(except minimal.py)" qualifier.

STATUS: GREEN
