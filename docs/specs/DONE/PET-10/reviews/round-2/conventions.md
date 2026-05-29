# PET-10 Conventions Review — Round 2

**Spec:** `docs/specs/TODO/PET-10.spec.md`
**Brief:** `docs/briefs/PET-10-jwt-license-premium-wiring.md`
**Round:** 2

---

## Closure of Round 1 Findings

| Finding | Status | Evidence |
|---------|--------|----------|
| R1/F-1 (P2) CLAUDE.md divergence | CLOSED | Deferred item 5 |
| R1/F-4 (P2) premium/__init__.py re-exports | CLOSED | Scope table line 29 |
| R1/F-6 (P2) validate_license vs CLAUDE.md | CLOSED | Deferred item 5 |
| R1/F-10 (P1) bare assert in _check_premium | CLOSED | Design §3 defensive guard |
| R1/F-13 (P2) mypy override merging | CLOSED | Design §6 explicit instruction |

## Findings

### F-1 — Wiki architecture.md and state.md also reference `petasos.activate(key)` (P2)

Deferred item 5 only mentions CLAUDE.md but `architecture.md` line 65 and `state.md` line 87 also say `petasos.activate(key: str)`. Should note all three sources need post-ship update.

### F-2 — `_DEFAULT_VALIDATOR` module-level global vs "no singleton" decision (P3)

Minor inconsistency: Decision says "Libraries shouldn't own singletons" but `_DEFAULT_VALIDATOR` is a module-level singleton. Functionally benign since validator is stateless.

### F-3 — `LicenseValidator` exported from `premium/__init__.py` but not `petasos/__init__.py` (P2)

Existing pattern: all public premium types are re-exported at top level (AlertManager, AuditEmitter, ToolCallGuard, etc.). Omitting `LicenseValidator` from `petasos/__init__.py` breaks this symmetry.

### F-4 — Hatch build auto-discovery of `.pem` file (P3)

Spec relies on Hatch auto-discovering `public.pem` inside a package but doesn't note the precedent (profiles JSON files work the same way).

### F-5 — Tri-state `"locked"` → `"disabled"` not in test plan for licensed+feature-off case (P2)

Tests asserting `"locked"` when premium active + feature toggled off should become `"disabled"`. Test plan only covers `"unlocked"` → `"available"`.

### F-6 — Wiki files need post-ship update (P2)

Same as F-1. `architecture.md` Interfaces section and `state.md` PET-10 entry need update.

STATUS: GREEN
