# PET-4 Spec Review — Correctness (Round 1)

**Spec:** `docs/specs/TODO/PET-4.spec.md` (v1)
**Brief:** `docs/briefs/PET-4-llamafirewallscanner-brief.md`
**Round:** 1

---

## Findings

### F-1 (P0) — Wrong ScannerType enum name for AlignmentCheck

Section 3 (`_ensure_loaded`) uses `ScannerType.ALIGNMENT_CHECK`. The actual LlamaFirewall enum value is `ScannerType.AGENT_ALIGNMENT`.

**Evidence:** LlamaFirewall source `llamafirewall/llamafirewall.py` defines `ScannerType` with `AGENT_ALIGNMENT`, not `ALIGNMENT_CHECK`. Using the wrong name will raise `AttributeError` at runtime.

**Fix:** Replace `ScannerType.ALIGNMENT_CHECK` with `ScannerType.AGENT_ALIGNMENT` in the `_COMPONENT_MAP` dict and anywhere else it appears.

### F-2 (P0) — Wrong Role enum name

Section 3 (`_ensure_loaded`) uses `Role.AGENT`. The actual LlamaFirewall enum value is `Role.ASSISTANT`.

**Evidence:** LlamaFirewall source defines `Role` enum with values including `USER`, `SYSTEM`, `TOOL`, `ASSISTANT`, `MEMORY`. There is no `Role.AGENT`.

**Fix:** Replace `Role.AGENT` with `Role.ASSISTANT` throughout the spec.

### F-3 (P1) — D8 rationale incomplete re: `asyncio.run()` inside LlamaFirewall

D8 describes LlamaFirewall's `scan()` as "synchronous." In reality, `LlamaFirewall.scan()` internally calls `asyncio.run()` to execute async scanner pipelines. This means wrapping it in `asyncio.to_thread()` is correct (it avoids the "cannot call asyncio.run() from a running event loop" error), but the rationale should be updated to reflect the true reason: `to_thread()` runs the call in a separate thread with its own event loop, avoiding the nested-event-loop conflict.

**Fix:** Amend D8 and the relevant design narrative to note that `LlamaFirewall.scan()` internally uses `asyncio.run()`, and `to_thread()` is needed specifically because you can't call `asyncio.run()` from within an already-running event loop.

### F-4 (P0) — Internal contradiction: two incompatible `_scan_sync` signatures

Section 5 presents two versions of `_scan_sync`:
1. First code block: returns `list[ScanFinding]` and raises `_ComponentErrors` on partial failure
2. "Revised" narrative + code: returns `tuple[list[ScanFinding], list[str]]` (findings + errors)

Section 4 (`scan()`) calls `asyncio.to_thread(self._scan_sync, text, direction)` and uses the result as `findings` (a list), matching version 1. But section 5's revised narrative says `_scan_sync` returns a tuple. These are incompatible. The spec must present one canonical design.

**Fix:** Remove the original version and keep only the tuple-return design. Update section 4's `scan()` to destructure the tuple: `findings, errors = await asyncio.to_thread(...)`.

---

## Closure Table

| Finding | Status | Notes |
|---------|--------|-------|
| F-1 | OPEN | Wrong enum name — runtime crash |
| F-2 | OPEN | Wrong enum name — runtime crash |
| F-3 | OPEN | Rationale gap — misleading |
| F-4 | OPEN | Contradictory code blocks |

STATUS: RED P0=3 P1=1
