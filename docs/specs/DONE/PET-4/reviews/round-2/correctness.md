# PET-4 Spec Review — Correctness (Round 2)

**Spec:** `docs/specs/TODO/PET-4.spec.md` (v2)
**Brief:** `docs/briefs/PET-4-llamafirewallscanner-brief.md`
**Round:** 2

---

## Closure of round 1 findings

| Finding | Status | Evidence |
|---------|--------|---------|
| R1 F-1 (P0) ScannerType.ALIGNMENT_CHECK wrong | CLOSED | spec section 3: `ScannerType.AGENT_ALIGNMENT` |
| R1 F-2 (P0) Role.AGENT wrong | CLOSED | spec section 3: `Role.ASSISTANT` |
| R1 F-3 (P1) D8 rationale incomplete | CLOSED | D8 now explains `asyncio.run()` nested-loop conflict |
| R1 F-4 (P0) Two incompatible _scan_sync signatures | CLOSED | Single tuple-return design in sections 4-5 |

## Findings

### F-1 (P3) — `_ensure_loaded` blocks event loop during first-use model download

`_ensure_loaded()` is called synchronously from async `scan()` before `asyncio.to_thread()`. First call triggers model downloads that block the event loop. Documented in spec section 3 narrative. PET-6 integration scope.

### F-2 (P3) — Plane ticket PET-4 not cached in memory server

Memory search returned 0 results. Non-blocking — brief is local source of truth.

### F-3 (P4) — `result.score is not None` guard is defensive but upstream types `score` as `float`

Defensively correct, won't cause bugs. Minor documentation nit.

### F-4 (P4) — Module structure stub doesn't show `ScanDecision` import

Correct — `ScanDecision` is imported inside `_ensure_loaded`, not at module level. No mismatch.

STATUS: GREEN
