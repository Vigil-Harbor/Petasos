# Conventions Review -- round 2

## Closure of round 1 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| conventions | F-1 | premium_features manifest format diverges from petasos-spec.md | CLOSED | Deferred section acknowledges and plans petasos-spec.md update |
| conventions | F-2 | activate()/deactivate() vs petasos.activate(key) convention | CLOSED | D12 addresses divergence |
| conventions | F-3 | PipelineResult docstring references PET-6 | CLOSED | Spec notes docstring will be updated to PET-7 |
| conventions | F-4 | Stage 12 rebuild omits premium fields | CLOSED | `_build_result()` helper |
| conventions | F-5 | FrequencyTracker always constructed in OSS | CLOSED | Deferred as P3 |
| conventions | F-6 | evaluate_tier import unused in escalation hook | CLOSED | Import removed |
| conventions | F-7 | FrequencyUpdateResult.tier embeds escalation knowledge | CLOSED | D5 revised |
| conventions | F-8 | Default tier2=30 equals TIER3_FLOOR=30 | CLOSED | Deferred as P4 |
| conventions | F-9 | Spec says 9 fields but lists 10 | CLOSED | Count corrected to 10 |
| conventions | F-10 | premium_features dict mutable on frozen dataclass | CLOSED | MappingProxyType |
| conventions | F-11 | Manifest pre-declares PET-8/9/10 features | CLOSED | Deferred with rationale |

## Findings

### F-1: `to_dict()`/`from_dict()` need note on frequency_weights handling
**Severity:** P2
**Where:** spec section 5.3
**Suggested fix:** Clarify that no `from_dict()` changes needed — dict serializes natively.

### F-2: Section 5.7 prose still says `petasos.activate(key)` for the scaffold
**Severity:** P2
**Where:** spec section 5.7
**Suggested fix:** Rewrite to say `pipeline.activate()` per D12.

### F-3: `MappingProxyType` import shown inline in two code blocks
**Severity:** P4
**Suggested fix:** Note import goes at top of each respective module.

### F-4: Double-gate pattern (license + config toggle) not authorized by brief
**Severity:** P2
**Where:** spec section 5.4
**Suggested fix:** Add rationale note explaining the double-gate pattern.

### F-5: `frequency_weights` defensive copy shallow copy rationale
**Severity:** P3
**Suggested fix:** Add parenthetical: "Shallow copy sufficient since values are float (immutable)."

### F-6: Config validation tests in integration file instead of test_config.py
**Severity:** P2
**Where:** spec "Files left alone" vs test plan
**Suggested fix:** Either move config tests to test_config.py or add note explaining placement.

### F-7: `premium/__init__.py` exports vs "internal implementation details" label
**Severity:** P3
**Suggested fix:** Clarify whether `petasos.premium` is a public or internal subpackage.

## Summary
P0: 0 | P1: 0 | P2: 4 | P3: 2 | P4: 1

STATUS: GREEN
