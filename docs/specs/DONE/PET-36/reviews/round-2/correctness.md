# Correctness Review — round 2

## Closure of round 1 findings
- correctness F-1 (stale HEAD) — CLOSED: L5 cites HEAD `d0af5aa`, files unchanged since `d927f4b` (verified via git log).
- correctness F-2 (mixed-case exempt) — CLOSED: Change 3 now `resolved.lower() in {e.lower() for e in self._profile.tool_exempt_list}`.
- correctness F-3 (premium gate) — CLOSED: `test_alias_exec_to_read_exempt_blocked` requires premium active + positive assertion.
- correctness F-4 (imports) — CLOSED: test-plan rows annotate imports.
- edge F-1 (P0, broke existing tests) — CLOSED: `name in self._profile.tool_alias_map` guard + D8; both pre-existing tests use empty own alias maps → guard never fires.
- edge F-2 (P1, gate asymmetry) — CLOSED: both gates profile-own.
- edge F-3/F-4/F-5/F-6 — CLOSED.
- conventions F-2 (ruff format) — CLOSED; F-1 (py-3.13) — PARTIAL/deferred with rationale.

## Findings
No findings.

## Core re-verification (against live source)
- Change 3 exploit trace (profile exec→read, exempt read, call exec): `"exec" ∈ profile map`, resolved="read", "read" ∈ exempt → suppress → returns "exec" → Step 4 miss → param scan. BLOCKED.
- Change 3 legitimate trace (exempt exec, empty own map, call bash): `"bash" ∉ {}` → condition false → resolved="exec" → Step 4 hit → exempt. PRESERVED.
- Change 1/2 snippets compile against real surrounding code (alias_map L73 loop L74-76; merged exempt L139-144 / alias L146-154 / return L156). isinstance guard + profile-named ValueError fit.
- Construction scope excludes DEFAULT_TOOL_ALIASES (defined only in guard.py; never merged into profiles).
- Internal consistency: Scope ↔ Decisions(+D8) ↔ Design ↔ Test plan ↔ Test command ↔ Done-when agree; 7 new tests reconcile (2/2/3 per file).
- All 7 brief Done-when covered; DW3's profile-introduced narrowing is the deliberate D8 resolution of edge F-1/F-2, not drift.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 0 | P4: 0

STATUS: GREEN
