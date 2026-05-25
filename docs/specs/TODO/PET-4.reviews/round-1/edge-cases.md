# PET-4 Spec Review — Edge Cases (Round 1)

**Spec:** `docs/specs/TODO/PET-4.spec.md` (v1)
**Brief:** `docs/briefs/PET-4-llamafirewallscanner-brief.md`
**Round:** 1

---

## Findings

### F-1 (P0) — Internal contradiction: two `_scan_sync` designs

Same as correctness F-4. Sections 4 and 5 present incompatible signatures for `_scan_sync`. The first version raises `_ComponentErrors`; the revised version returns a tuple. Section 4's `scan()` only handles the first version's return type.

**Fix:** Consolidate to one design. The tuple-return version is simpler and correctly preserves partial results.

### F-2 (P1) — Partial failure findings lost under original design path

Under the first `_scan_sync` design (raises `_ComponentErrors`), the outer `scan()` catches `Exception` and returns `ScanResult(findings=(), error=str(exc))` — losing any findings collected before the error. DS3 promises per-component error isolation with preserved partial findings, but the first code path contradicts that.

**Fix:** Already fixed by adopting the tuple-return design. But the spec must remove the contradictory first version entirely.

### F-3 (P2) — Empty string input behavior

The spec doesn't document what happens when `text=""`. LlamaFirewall's PromptGuard will likely return ALLOW for empty input, so `scan("")` should produce zero findings. Worth a test case but not a design gap.

### F-4 (P1) — No confidence clamping

The spec maps `result.score` directly to `ScanFinding.confidence`. If LlamaFirewall returns a score outside [0.0, 1.0] (e.g., a raw logit or miscalibrated value), the finding violates test 20's assertion `0.0 <= finding.confidence <= 1.0`.

**Fix:** Clamp confidence: `max(0.0, min(1.0, score))`.

### F-5 (P2) — No test for `session_id` parameter passthrough

The `scan()` signature accepts `session_id` but neither the design nor the tests mention what happens to it. Per the Scanner protocol it's accepted but can be ignored. A test documenting this is nice-to-have.

### F-6 (P1) — `result.decision.name` string comparison is fragile

Section 5 uses `result.decision.name != "ALLOW"` to check the verdict. This relies on the string representation of the enum, which could change if Meta renames the value. Importing and comparing against the enum value is more robust.

**Fix:** Import `ScanDecision` (or equivalent) and compare `result.decision != ScanDecision.ALLOW`.

### F-7 (P1) — Lock held during heavyweight model download

`_ensure_loaded()` holds `threading.Lock()` during the entire lazy-load, which includes `LlamaFirewall()` constructor calls. For PromptGuard, this triggers a ~180MB model download on first use. All concurrent `scan()` calls block on the lock until download completes.

**Fix:** Document this as a known first-scan latency cost. The lock is correct (prevents duplicate downloads), but the spec should note that first-scan latency may be minutes on slow connections due to model download within the lock. A `petasos warmup` CLI is noted as out-of-scope.

### F-8 (P2) — GIL dependency in double-checked lock

The double-checked locking pattern (`if self._loaded` before and inside lock) relies on Python's GIL for the outer check's safety on `bool` reads. This is correct for CPython but worth a one-line note for future-proofing (e.g., if nogil/free-threaded Python is used).

### F-9 (P1) — `scanners/__init__.py` uses replacement semantics

Section 7 shows `__all__ = ["LlamaFirewallScanner"]` in `petasos/scanners/__init__.py`. If PET-3 (LlmGuardScanner) or PET-5 (PresidioScanner) ship first, this overwrites their exports. Should be additive.

**Fix:** Use additive exports that don't clobber existing scanner re-exports. Each scanner wrapper appends to whatever's already in `__init__.py`.

### F-10 (P2) — Cache message type classes

Section 5 re-imports `UserMessage` and `AssistantMessage` inside `_scan_sync()`, which runs on every call. These could be cached in `_ensure_loaded()` alongside the component instances.

### F-11 (P2) — `MappingProxyType` for `_COMPONENT_TAXONOMY`

`_COMPONENT_TAXONOMY` is a module-level mutable dict. For consistency with the "frozen exports" invariant in CLAUDE.md, consider wrapping it in `types.MappingProxyType`.

### F-12 (P0) — `_ComponentErrors` exception referenced but never defined

Section 5's first code path raises `_ComponentErrors(errors)`, but this exception class is never defined anywhere in the spec.

**Fix:** Either define it or (better) remove it by adopting the tuple-return design.

---

## Closure Table

| Finding | Status | Notes |
|---------|--------|-------|
| F-1 | OPEN | Same root cause as correctness F-4 |
| F-2 | OPEN | Partial-failure path loses findings |
| F-3 | OPEN | P2 — empty string test |
| F-4 | OPEN | Confidence clamping needed |
| F-5 | OPEN | P2 — session_id test |
| F-6 | OPEN | Fragile string comparison |
| F-7 | OPEN | Lock hold during download |
| F-8 | OPEN | P2 — GIL note |
| F-9 | OPEN | Replacement vs additive exports |
| F-10 | OPEN | P2 — cache message classes |
| F-11 | OPEN | P2 — MappingProxyType |
| F-12 | OPEN | Undefined exception class |

STATUS: RED P0=2 P1=4
