# Conventions Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: premium_features manifest format diverges from petasos-spec.md
**Severity:** P2
**Where:** spec section 5.5 vs petasos-spec.md
**Suggested fix:** Add decision noting format change from list-of-dicts to dict.

### F-2: activate()/deactivate() as Pipeline methods vs petasos.activate(key) convention
**Severity:** P2
**Where:** spec section 5.7 vs CLAUDE.md/README
**Suggested fix:** Acknowledge divergence, decide instance vs module-level. (Duplicate of correctness F-5.)

### F-3: PipelineResult docstring references PET-6 but PET-7 adds the fields
**Severity:** P4
**Suggested fix:** Update docstring reference.

### F-4: Stage 12 rebuild omits premium fields
**Severity:** P1
**Where:** spec section 5.4 vs pipeline.py lines 299-307
**Suggested fix:** Both construction sites must include premium fields. (Triplicate of correctness F-2.)

### F-5: FrequencyTracker always constructed in OSS installations
**Severity:** P3
**Suggested fix:** Note as acceptable. (Duplicate of edge-cases F-11.)

### F-6: evaluate_tier import unused in escalation hook
**Severity:** P2
**Suggested fix:** Remove dead import. (Triplicate of correctness F-3.)

### F-7: FrequencyUpdateResult.tier embeds escalation knowledge, partially contradicts D5
**Severity:** P3
**Suggested fix:** Soften D5 text to match reality.

### F-8: Default tier2=30 equals TIER3_FLOOR=30 -- valid but tight
**Severity:** P4

### F-9: Spec says 9 fields but lists 10
**Severity:** P4
**Suggested fix:** Fix count. (Duplicate of correctness F-1.)

### F-10: premium_features dict mutable on frozen dataclass
**Severity:** P2
**Suggested fix:** Use MappingProxyType or document. (Duplicate of edge-cases F-1.)

### F-11: Manifest pre-declares PET-8/9/10 features without noting it as a spec addition
**Severity:** P3
**Suggested fix:** Add rationale note.

## Summary
P0: 0 | P1: 1 | P2: 4 | P3: 3 | P4: 3

STATUS: RED P0=0 P1=1 P2=4 P3=3 P4=3
