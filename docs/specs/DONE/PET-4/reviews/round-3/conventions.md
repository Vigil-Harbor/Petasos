# PET-4 Spec Review — Conventions (Round 3)

**Spec:** `docs/specs/TODO/PET-4.spec.md` (v3)
**Brief:** `docs/briefs/PET-4-llamafirewallscanner-brief.md`
**Round:** 3

---

## Closure of round 2 findings

| Finding | Status | Evidence |
|---------|--------|---------|
| R2 F-1 (P2) `scanners/__init__.py` pattern diverges from PET-3 | CLOSED | Harmonized with PET-3's try/except guarded import pattern |
| R2 F-2 (P2) Top-level `petasos/__init__.py` export contradicts PET-3 | CLOSED | `petasos/__init__.py` not modified; ML scanners via `petasos.scanners` only |
| R2 F-3–F-7 (P3) Silent spec additions | CLOSED | All well-documented spec-level additions with rationale |

## Findings

### F-1 (P3) — Lazy-load pattern diverges slightly from PET-3's `_ensure_loaded` signature

PET-3's `_ensure_loaded()` returns `None` and sets `self._load_error`; PET-4's returns `bool` and sets `self._load_error`. Both are valid patterns — PET-4's is slightly more ergonomic (caller checks return value instead of `self._load_error is None`). Not a conformance issue since the Scanner protocol doesn't specify internal methods.

### F-2 (P3) — `MappingProxyType` vs `frozenset` for taxonomy immutability

PET-4 uses `MappingProxyType` for `_COMPONENT_TAXONOMY`, PET-1 uses `frozenset` for `RULE_TAXONOMY`. Both satisfy the CLAUDE.md "frozen exports" invariant. `MappingProxyType` is correct for dict-shaped data; `frozenset` is correct for set-shaped data. No inconsistency.

### F-3 (P4) — `from __future__ import annotations` present in spec section 1 but not section 7

The module structure (section 1) includes `from __future__ import annotations`. The `scanners/__init__.py` block (section 7) does not. The `__init__.py` file doesn't use annotations that benefit from PEP 563 (no forward refs, no complex type expressions), so omission is acceptable.

### F-4 (P3) — No `reset()` method for re-initialization

PET-3's spec includes a `reset()` method that clears lazy-load state, enabling test isolation and re-initialization after config changes. PET-4 does not include this method. For consistency, PET-4 should consider adding `reset()` in a future revision. Not blocking — test isolation can use fresh instances.

### F-5 (P4) — Test command matches CLAUDE.md convention

Explicit Python path, module-form pytest invocation, verbose + short traceback flags. Matches PET-3 and CLAUDE.md guidance.

STATUS: GREEN
