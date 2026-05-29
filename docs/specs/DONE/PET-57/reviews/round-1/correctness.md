# Correctness Review -- round 1

## Findings

### F-1: Attack vector framing implies `resolve(dict)` reaches `_parse_profile` -- spec should clarify the actual exposure path
**Severity:** P3
**Where:** spec.md:10-11 (Goal section)
The brief's attack scenario claims `Pipeline(config=PetasosConfig(profile=my_dict))` -> `ProfileResolver.resolve()` -> `_parse_profile`. In reality, `resolve(dict)` dispatches to `_merge_with_base` (already safe). `_parse_profile` is only called from `_load_builtins` (json.loads output, no external ref). The fix targets `_parse_profile` as defense-in-depth for direct callers (tests, integrators).

### F-2: Ticket MCP record shows "review status: refuted" -- informational
**Severity:** P3
**Where:** Plane ticket metadata
The MCP record for PET-57 includes "Review status: refuted." This likely refers to the initial red-team triage phase, not a decision to reject the fix. Brief says "Backlog -> ready-for-dev," confirming the ticket is active.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 2 | P4: 0

STATUS: GREEN
