# Correctness Review -- round 3

## Closure of round 2 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| correctness | F-1 | Third PipelineResult construction site | CLOSED | spec section 5.4: explicit 3-site enumeration |
| correctness | F-2 | `finding_types` naming inconsistency | CLOSED | renamed to `rule_ids` throughout |
| correctness | F-3 | `to_dict()`/`from_dict()` round-trip note | CLOSED | serialization note added |
| correctness | F-5 | `_match_weight` glob stripping convention | CLOSED | explicit partitioning rule |
| edge-cases (all) | | All round 2 edge-cases findings | CLOSED | see closures above |
| conventions (all) | | All round 2 conventions findings | CLOSED | see closures above |

## Findings

### F-1: `_match_weight` parameter still named `finding_type`
**Severity:** P4
**Where:** spec section 5.1 line 162
**Suggested fix:** Rename to `rule_id` for consistency with public API.

### F-2: Ticket not cached in MCP memory
**Severity:** P3

### F-3: Constructor says "extracts fields" but `evaluate_tier` needs full config reference
**Severity:** P3
**Suggested fix:** Amend to "Stores a reference to PetasosConfig and extracts frequency-relevant fields for fast access."

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 2 | P4: 1

STATUS: GREEN
