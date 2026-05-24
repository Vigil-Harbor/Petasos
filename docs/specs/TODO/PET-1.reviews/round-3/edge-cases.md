# PET-1 Spec Review — Edge Cases (Round 3)

**Spec:** `docs/specs/TODO/PET-1.spec.md`
**Brief:** `docs/briefs/PET-1-brief.md`
**Round:** 3

---

## Closure of round 2 findings

All R2 P1 finding (confusables_normalized) CLOSED. R2 P2 items deferred in spec.

---

## Findings

### F-1 [P2] Escalation rule wording should say "non-suppressed" injection rule

Line 415: "If invisible-chars fires AND any injection rule also fires" — should say "any non-suppressed injection rule" for consistency with D7 point 3.

### F-2 [P3] Empty string normalize test should assert all metadata flags

### F-3 [P3] ScanFinding.confidence has no clamping

### F-4 [P3] Position with start >= end is unconstrained

### F-5 [P3] ScanResult.duration_ms timing instrumentation unspecified

### F-6 [P3] from_dict() error handling for missing/extra keys unspecified

---

STATUS: GREEN
