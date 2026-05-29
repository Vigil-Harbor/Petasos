# Conventions Review — round 2

## Closure of round 1 findings
- conventions F-1 (py-3.13 form) — PARTIAL: retained, now documented in `## Deferred (P2+)` with rationale (bare python=3.10 fails requires-python). Class-(c) documented deviation.
- conventions F-2 (ruff format) — CLOSED: test command chains `ruff format --check .`; Done-when lists it.
- conventions F-3/F-4 (D7/D6 validations) — CLOSED.
- correctness F-1/2/3/4 — CLOSED. edge F-1(P0)/F-2(P1)/F-3/F-4/F-5/F-6 — CLOSED.

## Findings

### F-1: `## Deferred (P2+)` precedes `## Out of scope` — reverses sibling house-style — P2
PET-8/9/10/11 all place `## Out of scope` BEFORE `## Deferred (P2+)`. PET-36 inverts them. (The review-prompt's stated ordering lists Deferred first, so the spec is internally defensible, but it diverges from the four shipped sibling specs.) Cosmetic; both sections present and correct.
**Fix:** move `## Deferred (P2+)` to sit after `## Out of scope`.

### F-2: Deferred items appropriately scoped (validation) — P3
Both items (Step-4 case-sensitivity; py-3.13 form) match PET-10's Deferred style with reviewer-round attribution; genuinely P2+ and out of GUARD-03 scope.

### F-3: D8 + isinstance guard not over-engineering (validation) — P3
D8 narrows an existing check (no new machinery); isinstance(v,str) matches the sibling type-guard style in `_merge_with_base` (L97/104/111/135/142/149). Profile-named ValueError matches existing prefixed-f-string raises.

### F-4: CLAUDE.md invariants respected (validation) — P3
Frozen exports (no JSON edited, DEFAULT unchanged, MappingProxyType preserved, fallback no-mutation); OSS/premium split (all under premium/); "never throws" applies to evaluate()/inspect() not construction — added ValueErrors are construction-time; `_normalize_tool_name` still returns a string (isinstance guard prevents the latent .strip() AttributeError). No wiki decision contradicts D8.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 3 | P4: 0

STATUS: GREEN
