# PET-5 Spec Review — Conventions (Round 2)

**Spec:** `docs/specs/TODO/PET-5.spec.md` (v2)
**Brief:** `docs/briefs/PET-5-presidioscanner-brief.md`
**Reviewer:** spec-reviewer-conventions
**Round:** 2

---

## Closure of round 1 findings

All round 1 findings CLOSED. No P1/P2 items remain.

---

## Findings

### F-1 (P3) — PET-4 sibling convention divergence in `_ensure_loaded()` pattern

PET-5 matches PET-3 (raises), PET-4 returns bool. Acknowledged divergence. No change needed for PET-5.

### F-2 (P4) — Spec says "matching PET-3/4" for re-export but PET-4 uses bare import

Change to "matching PET-3".

### F-3 (P3) — `__all__` management with try/except not specified

If import fails, names won't be defined but may be in `__all__`. Append entries inside try block.

### F-4 (P3) — Spec additions have clear rationale (transparency audit)

Custom HMAC operator, entity-scoped counters, mask visible=4 — all well-reasoned.

### F-5 (P3) — `_SEVERITY_MAP` described as "frozen lookup" but is a plain dict

CLAUDE.md frozen exports invariant. Private `_` prefix makes mutation unlikely. Pragmatic choice to leave as dict.

---

STATUS: GREEN
