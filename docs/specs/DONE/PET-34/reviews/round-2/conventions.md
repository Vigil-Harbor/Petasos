# Conventions Review -- Round 2

## Closure of round 1 findings

All 8 round-1 conventions findings closed. Cross-lens closure verified.

## Findings

### F-1: "Relationship to PET-30" misattributes guard-side fix to PET-34 (P2)
PET-30 spec and wiki state.md confirm the guard-side `_derive_tier()` fix shipped in PET-30 (commit b8f9ad4). PET-34's new work is only the TTL defensive tombstone (D7).

### F-2: Files-changed table doesn't distinguish shipped vs pending (P3)
Same as edge-cases F-1. Table should annotate PET-30 shipped vs PET-34 new.

### F-3: All brief departures properly flagged (P4)
Positive observation. D3 and D6 marked "Departs from brief." No silent additions.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 1 | P4: 1

STATUS: GREEN
