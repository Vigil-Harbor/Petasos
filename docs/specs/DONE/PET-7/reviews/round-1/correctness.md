# Correctness Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: Config field count says 9 but code block lists 10
**Severity:** P1
**Where:** spec section 5.3, line 200
**Claim:** "Add 9 new fields to `PetasosConfig`:"
**Why this is wrong:** The code block lists 10 fields: `frequency_half_life_seconds`, `frequency_weights`, `rolling_window_seconds`, `rolling_threshold`, `tier1_threshold`, `tier2_threshold`, `tier3_threshold`, `max_sessions`, `session_ttl_seconds`, `max_new_sessions_per_minute`. The prose count is wrong.
**Suggested fix:** Change "Add 9 new fields" to "Add 10 new fields".

### F-2: PipelineResult rebuild path at stage 12 loses premium fields
**Severity:** P0
**Where:** spec section 5.4
**Claim:** The spec shows premium fields added to ONE PipelineResult construction and does not address the rebuild path.
**Why this is wrong:** In current `pipeline.py` (lines 279-307), there are two PipelineResult constructions. The stage 12 rebuild (line 301) only fires when audit/alert hooks add errors, but the rebuild does NOT include premium fields -- they revert to None defaults.
**Suggested fix:** Add explicit guidance that the rebuild must also include `escalation_tier`, `session_score`, and `premium_features`.

### F-3: Escalation hook imports `evaluate_tier` but never calls it -- dead import
**Severity:** P2
**Where:** spec section 5.4, escalation hook code
**Claim:** The hook contains `from petasos.premium.escalation import evaluate_tier` but reads tier from `self._last_freq_result.tier`.
**Why this is wrong:** Unused import will trigger ruff F401.
**Suggested fix:** Remove the import from the hook code.

### F-4: Spec contradicts itself on where FrequencyTracker is imported in pipeline.py
**Severity:** P1
**Where:** spec section 5.4
**Claim:** Prose says "top of module (not deferred)" but code block shows import inside `__init__`.
**Why this is wrong:** Contradictory guidance. Also, `FrequencyUpdateResult` type annotation needs import resolution for mypy.
**Suggested fix:** Pick one location and be consistent. Top-of-module with TYPE_CHECKING guard for the type annotation.

### F-5: `activate()` / `deactivate()` not listed in scope table + API shape mismatch with CLAUDE.md
**Severity:** P1
**Where:** spec section 5.7 vs. Scope table and CLAUDE.md
**Claim:** Section 5.7 defines `activate()` and `deactivate()` on Pipeline. CLAUDE.md documents `petasos.activate(key)` as module-level.
**Why this is wrong:** Scope table omits these methods. API shape differs from documented convention.
**Suggested fix:** Add to scope table. Decide pipeline-level vs module-level and document the decision.

### F-6: Brief done-when allows ValueError OR clamp; spec chose ValueError
**Severity:** P2
**Where:** spec Done when vs brief Done when
**Why this is wrong:** Not a bug -- spec correctly narrows the brief's option. Noted for completeness.

### F-7: `evaluate_tier()` called inside tracker creates frequency->escalation import dependency
**Severity:** P3
**Where:** spec section 5.1 step 9
**Suggested fix:** Note the import dependency in the spec.

### F-8: Ticket not in MCP memory store
**Severity:** P3

### F-9: `_build_premium_features()` always returns dict, so `premium_features` is never None for pipeline results
**Severity:** P2
**Suggested fix:** Clarify that `premium_features` is always populated by pipeline, `None` only for external construction.

### F-10: Frozen dataclass `PetasosConfig` needs `object.__setattr__` for `frequency_weights` defensive copy
**Severity:** P1
**Where:** spec section 5.3
**Why this is wrong:** Direct assignment in `__post_init__` raises `FrozenInstanceError`.
**Suggested fix:** Show `object.__setattr__` call matching existing `pii_entities` pattern.

## Summary
P0: 1 | P1: 3 | P2: 2 | P3: 2

STATUS: RED P0=1 P1=3 P2=2 P3=2
