# Edge-Cases Review -- round 3

## Closure of round 2 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| edge-cases | F-1 | Empty frequency_weights={} | CLOSED (deferred) | Deferred section |
| edge-cases | F-2 | Eviction by oldest allows attacker bypass | CLOSED (deferred) | Deferred section |
| edge-cases | F-3 | Glob stripping convention | CLOSED | Explicit partitioning rule in constructor |
| edge-cases | F-4 | MappingProxyType not JSON-serializable | CLOSED | Serialization note added |
| edge-cases | F-5 | Third PipelineResult construction site | CLOSED | 3-site enumeration |
| edge-cases | F-6 | Rate limit interaction with TTL eviction | CLOSED | Implicit; rate limit is backstop |
| edge-cases | F-7 | Rolling window pruning | CLOSED | Pruning moved outside rule_ids guard |
| edge-cases | F-8 | Rate limit window hardcoded | CLOSED (deferred) | Deferred section |
| edge-cases | F-9 | finding_types naming | CLOSED | Renamed to rule_ids |
| edge-cases | F-10 | clear() resetting creation timestamps | CLOSED | Documented |

## Findings

### F-1: `_match_weight` parameter still named `finding_type`
**Severity:** P4
**Where:** spec section 5.1
**Suggested fix:** Rename to `rule_id` for consistency.

### F-2: Circular import between config.py and escalation.py for TIER3_FLOOR
**Severity:** P2
**Where:** spec section 5.3 validation rule 5 vs section 5.2
**Edge case:** `config.py` needs `TIER3_FLOOR` from `escalation.py`, which imports `PetasosConfig` from `config.py`. Circular import.
**Suggested fix:** Define `TIER3_FLOOR` in a shared location (e.g., `_types.py`), or hardcode 30.0 in config.py with a cross-referencing test.

### F-3: `evaluate_tier` takes full PetasosConfig but only needs three thresholds
**Severity:** P3
**Where:** spec section 5.2
**Suggested fix:** Consider accepting three floats. Deferred to PET-8.

### F-4: NaN score from accumulated inf not handled
**Severity:** P2
**Where:** spec section 5.1 step 6
**Edge case:** Many high-weight findings in rapid succession can accumulate to inf; subsequent math produces nan, silently disabling escalation.
**Suggested fix:** Add post-update score clamp or isfinite check.

### F-5: Threshold fields not checked for finiteness
**Severity:** P2
**Where:** spec section 5.3 validation rules 4-5
**Edge case:** `tier3_threshold=float('inf')` passes validation but makes Tier 3 unreachable, violating the "cannot be disabled" invariant.
**Suggested fix:** Add explicit finite check on all three threshold fields.

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 1 | P4: 1

STATUS: GREEN
