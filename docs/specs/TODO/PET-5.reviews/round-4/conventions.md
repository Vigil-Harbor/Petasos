# PET-5 Spec Review — Conventions (Round 4)

**Spec:** `docs/specs/TODO/PET-5.spec.md` (v4)
**Brief:** `docs/briefs/PET-5-presidioscanner-brief.md`
**Reviewer:** spec-reviewer-conventions
**Round:** 4

---

## Closure of round 3 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | Top-level `petasos/__init__.py` re-export diverges from PET-3 | CLOSED | spec line 45: "not modified — matching PET-3's convention" |
| F-2 | `_ensure_loaded()` omits threading.Lock | CLOSED | spec line 104: `self._load_lock` with threading.Lock |
| F-3 | PET-3 `_ensure_loaded()` characterization | PARTIAL | spec line 102: "catch-cache-reraise" — PET-3 actually catches-caches-returns (no reraise). See F-1 below. |
| F-4 | No explicit handling of Presidio Hash salt behavior | CLOSED | spec line 179: non-determinism documented |
| F-5 | `anonymize()` docstring convention | CLOSED | Deferred line 384 |

---

## Findings

### F-1 (P3) — `_ensure_loaded()` characterization still misaligns with PET-3

PET-3's `_ensure_loaded()` catches-stores-returns silently (no raise). PET-5 says `_ensure_loaded()` raises and `scan()` catches, then calls this the "catch-cache-reraise pattern" matching PET-3. The patterns differ structurally but produce the same observable behavior. Spec should acknowledge the divergence rather than claim alignment.

### F-2 (P3) — `_SEVERITY_MAP` frozen-ness not specified

CLAUDE.md says "Frozen exports." A plain `dict` is mutable. PET-4 uses `MappingProxyType`. Either wrap in `MappingProxyType` or note that private `_` prefix makes defensive immutability unnecessary.

### F-3 (P4) — `from __future__ import annotations` not in code samples

All existing `.py` files use it. PET-3/PET-4 specs include it. PET-5 omits it in code samples. Implementer will likely add it anyway.

### F-4 (P4) — No `reset()` method discussed

PET-3 includes `reset()` for test isolation. PET-4 explicitly defers it. PET-5 neither includes nor defers — add a line in Deferred.

---

STATUS: GREEN
