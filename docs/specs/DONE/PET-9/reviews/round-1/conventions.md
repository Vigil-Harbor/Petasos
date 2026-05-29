# Conventions Review — Round 1

## Findings

### F-1: `AuditEvent.payload` and `Alert.context` use mutable `dict[str, Any]` on frozen dataclasses
**Severity:** P2
**Where:** spec section types
**Convention violated:** CLAUDE.md "Frozen exports" invariant
**Suggested fix:** Use MappingProxyType[str, Any] or wrap at construction time.

### F-2: `petasos/__init__.py` not listed in "Files to modify"
**Severity:** P2
**Convention violated:** Every premium type is re-exported from top-level __init__.py
**Suggested fix:** Add petasos/__init__.py to the files-to-modify table.

### F-3: `AuditEmitter` constructor takes raw `verbosity` instead of `config: PetasosConfig`
**Severity:** P2
**Convention violated:** Existing premium module constructor pattern (FrequencyTracker, ToolCallGuard take config)
**Suggested fix:** Change to accept config: PetasosConfig and read audit_verbosity internally.

### F-4: Spec introduces RuntimeError wrapping pattern, not used elsewhere
**Severity:** P3
**Suggested fix:** Consider letting exceptions propagate naturally or document rationale.

### F-5: Callbacks on Pipeline constructor vs parent spec placing them on PetasosConfig
**Severity:** P3
**Suggested fix:** Add a Decision section acknowledging the deviation from parent spec.

### F-6: Brief says two tier_escalation transitions, spec expands to three
**Severity:** P3
**Suggested fix:** Add a note acknowledging this as a spec-level addition with rationale.

### F-7: Redundant double-gate pattern not specified consistently
**Severity:** P4

### F-8: `alert_high_severity_threshold` should use Literal type not bare str
**Severity:** P2
**Convention violated:** Existing PetasosConfig uses Literal types for constrained fields
**Suggested fix:** Change to Literal["critical", "high", "medium", "low", "info"].

## Summary
P0: 0 | P1: 0 | P2: 4 | P3: 3 | P4: 1

STATUS: GREEN
