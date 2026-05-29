# PET-4 Spec Review — Correctness (Round 3)

**Spec:** `docs/specs/TODO/PET-4.spec.md` (v3)
**Brief:** `docs/briefs/PET-4-llamafirewallscanner-brief.md`
**Round:** 3

---

## Closure of round 2 findings

| Finding | Status | Evidence |
|---------|--------|---------|
| R2 F-1 (P3) `_ensure_loaded` blocks event loop | CLOSED | Documented in spec section 3 narrative, PET-6 scope |
| R2 F-2 (P3) Plane ticket not in MCP memory | CLOSED | Non-blocking — brief is local source of truth |
| R2 F-3 (P4) `result.score is not None` guard defensive | CLOSED | Defensively correct, no change needed |
| R2 F-4 (P4) Module structure stub `ScanDecision` import | CLOSED | Correct — imported inside `_ensure_loaded` |

## Findings

### F-1 (P2) — `scanners/__init__.py` code block omits `from __future__ import annotations`

The spec's section 7 code block for `petasos/scanners/__init__.py` does not include `from __future__ import annotations`. Consistent with the current codebase (the existing empty `__init__.py` doesn't have it either), but PET-3's spec includes it. Minor inconsistency between siblings.

### F-2 (P3) — `_ensure_loaded` first-call blocks event loop thread

`_ensure_loaded()` is called synchronously from `scan()` before `asyncio.to_thread()`. The first call triggers model downloads that block the event loop. Already documented in spec section 3 narrative and Deferred. PET-6 integration scope.

### F-3 (P3) — Plane ticket PET-4 still not cached in MCP memory

Memory search returned 0 results across rounds. Non-blocking — brief is the local source of truth per spec-cycle fallback.

### F-4 (P4) — `result.score is not None` guard is defensive but harmless

Upstream types `score` as `float`. The `is not None` guard adds a null-safe fallback. Defensively correct.

STATUS: GREEN
