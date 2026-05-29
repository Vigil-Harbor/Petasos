# Correctness Review -- round 2

## Closure of round 1 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| correctness | F-1 | Config field count says 9 but lists 10 | CLOSED | spec section 5.3: "Add 10 new fields to `PetasosConfig`:" |
| correctness | F-2 | PipelineResult rebuild at stage 12 loses premium fields | CLOSED | spec section 5.4: `_build_result()` helper introduced, both construction sites use it |
| correctness | F-3 | Escalation hook imports evaluate_tier but never calls it | CLOSED | spec section 5.4: escalation hook code no longer imports `evaluate_tier` |
| correctness | F-4 | FrequencyTracker import contradiction | CLOSED | spec section 5.4: "Import at the top of `pipeline.py` (not deferred inside `__init__`)" — no contradiction |
| correctness | F-5 | activate()/deactivate() missing from scope table + API mismatch | CLOSED | scope table adds "New public methods on Pipeline"; D12 addresses divergence |
| correctness | F-6 | Brief allows ValueError OR clamp; spec chose ValueError | CLOSED | D6 documents the choice |
| correctness | F-7 | evaluate_tier import dependency | CLOSED | D5 revised to acknowledge minimal coupling |
| correctness | F-8 | Ticket not in MCP memory | OPEN | Environmental, not a spec defect (P3) |
| correctness | F-9 | _build_premium_features() always returns dict | CLOSED | spec section 5.5 clarifies: None only for external construction |
| correctness | F-10 | Frozen dataclass needs object.__setattr__ | CLOSED | spec section 5.3 shows `object.__setattr__` pattern matching `pii_entities` |

## Findings

### F-1: Third PipelineResult construction site (outer exception handler) not addressed
**Severity:** P2
**Where:** spec section 5.4, scope table
**Claim:** "update **both** PipelineResult construction sites (initial + stage-12 rebuild)"
**Why this is wrong:** There are actually THREE `PipelineResult(...)` construction sites in `pipeline.py`: line 183 (outer `inspect()` exception handler), line 279 (inner initial), and line 301 (inner rebuild). The spec's `_build_result()` helper covers lines 279 and 301 but does not mention the outer handler. The outer handler creates `PipelineResult(safe=False, ...)` with all premium fields as `None` defaults. This is defensible behavior for a catastrophic-failure path, but should be explicitly acknowledged.
**Suggested fix:** Change "both" to "the two PipelineResult construction sites in `_inspect_inner()`" and add a note: "The outer exception handler in `inspect()` constructs PipelineResult directly with `None` defaults — intentional since no premium processing ran."

### F-2: `finding_types` parameter naming inconsistency
**Severity:** P4
**Where:** spec section 5.4
**Suggested fix:** Consider renaming to `rule_ids` in both hook code and `FrequencyTracker.update()` signature.

### F-3: `to_dict()`/`from_dict()` round-trip note for `frequency_weights`
**Severity:** P2
**Where:** spec section 5.3
**Suggested fix:** Add note: "No special `from_dict()` handling needed — JSON dicts deserialize directly to Python dicts."

### F-4: Ticket not cached in MCP memory
**Severity:** P3

### F-5: `_match_weight` glob stripping convention not shown in constructor
**Severity:** P2
**Where:** spec section 5.1
**Suggested fix:** Add: "Glob keys are identified by a trailing `'.*'` suffix. The constructor strips this suffix to produce the prefix stored in `self._glob_weights`."

### F-6: Brief done-when test count >= 40 vs spec >= 42
**Severity:** P3
**Suggested fix:** No action required — spec's higher threshold exceeds the brief's floor.

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 2 | P4: 1

STATUS: GREEN
