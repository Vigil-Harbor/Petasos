# PET-4 Spec Review — Conventions (Round 2)

**Spec:** `docs/specs/TODO/PET-4.spec.md` (v2)
**Brief:** `docs/briefs/PET-4-llamafirewallscanner-brief.md`
**Round:** 2

---

## Closure of round 1 findings

| Finding | Status | Evidence |
|---------|--------|---------|
| R1 F-1 (P2) DS4 enum name | CLOSED | `HUMAN_IN_THE_LOOP_REQUIRED` in DS4 |
| R1 F-2 (P2) DS1 cross-reference | CLOSED | D1 and DS1 cross-reference brief criterion |
| R1 F-3 (P2) MappingProxyType | CLOSED | Applied in sections 1/6 |

## Findings

### F-1 (P2) — `scanners/__init__.py` pattern diverges from PET-3 sibling spec

PET-3 uses try/except guarded import with explicit `__all__` construction. PET-4 uses bare import with `globals()` splat. Both work but the patterns should be harmonized across siblings.

### F-2 (P2) — Top-level `petasos/__init__.py` export contradicts PET-3 convention

PET-3 spec explicitly says ML-backend scanners are available via `petasos.scanners`, not the top-level namespace. PET-4 adds `LlamaFirewallScanner` to top-level `petasos/__init__.py`. Should match PET-3's approach.

### F-3–F-7 (P3) — Silent spec additions (DS1, DS2, DS3, per-component attribution, partial failure)

All category (c): spec-level additions with explicit rationale. Sound and well-documented.

STATUS: GREEN
