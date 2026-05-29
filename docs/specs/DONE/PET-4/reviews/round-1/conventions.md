# PET-4 Spec Review — Conventions (Round 1)

**Spec:** `docs/specs/TODO/PET-4.spec.md` (v1)
**Brief:** `docs/briefs/PET-4-llamafirewallscanner-brief.md`
**Round:** 1

---

## Findings

### F-1 (P2) — DS4 decision enum name

DS4 references `HUMAN_REQUIRED` as a possible LlamaFirewall decision state. The actual enum value is `HUMAN_IN_THE_LOOP_REQUIRED`. Not a P1 since the design handles it correctly (any non-ALLOW → finding), but the example name should be accurate.

### F-2 (P2) — DS1 cross-reference to brief criterion

The brief's Done When includes "Dynamic `scanners` dict built from enable flags." DS1 implements this via per-component instances rather than a single scanners dict. The spec should explicitly note that DS1's per-component approach satisfies this criterion and why the brief's phrasing (single dict) was adapted.

### F-3 (P2) — `_COMPONENT_TAXONOMY` mutability

Module-level `_COMPONENT_TAXONOMY` dict is mutable. CLAUDE.md states "built-in profiles, rules, and default configs must be immutable (defensive copies, frozen dataclasses)." Consider `types.MappingProxyType` or a frozen approach.

### F-4 (P2) — Spec follows PET-1 structure conventions

Verified: Goal, Scope, Decisions, Design (numbered), Test plan (numbered), Test command, Done when, Out of scope. Matches PET-1.spec.md format. No issues.

### F-5 (P2) — Test command uses explicit Python path

Good practice per CLAUDE.md: "Pin the interpreter explicitly when the project has multiple Python installs on PATH (common on Windows)."

---

## Closure Table

| Finding | Status | Notes |
|---------|--------|-------|
| F-1 | OPEN | P2 — enum name accuracy |
| F-2 | OPEN | P2 — cross-reference clarity |
| F-3 | OPEN | P2 — immutability convention |
| F-4 | N/A | Positive observation |
| F-5 | N/A | Positive observation |

STATUS: GREEN
