# PET-10 Correctness Review — Round 3

**Spec:** `docs/specs/TODO/PET-10.spec.md`
**Brief:** `docs/briefs/PET-10-jwt-license-premium-wiring.md`
**Round:** 3

---

## Closure of Round 2 Findings

| Finding | Status | Evidence |
|---------|--------|----------|
| R2/F-1 (P2) premium/__init__.py re-exports gap | CLOSED | Spec scope table line 29 lists premium/__init__.py; Design §4 covers top-level exports |
| R2/F-2 (P4) test plan item 39 duplicates item 34 | CLOSED | Item 39 now specifies 3 concrete test_pipeline.py tests by name |
| R2/F-3 (P3) Plane ticket not cached | CLOSED | Advisory — no spec change needed |

## Findings

### F-1 — Scope table activate() count says 37 but actual count is ~34 (P4)

Minor discrepancy in the scope table description for test_premium_integration.py. The count "37 existing `activate()` calls" may not exactly match the current file after PET-9 merge. Cosmetic — implementer will grep and update all occurrences regardless of count.

### F-2 — Scope table line 27 omits LicenseValidator from petasos/__init__.py additions (P4)

Scope table line 27 lists `LicenseState, LicenseClaims, validate_license` but Design §4 also adds `LicenseValidator`. Minor omission — Design §4 is authoritative and the implementer will follow it.

### F-3 — Test plan item 39 references test_pipeline.py but file has zero "unlocked" strings (P3)

Item 39 was revised to enumerate 3 specific `p.activate()` calls by test name, which is correct. The item title still says "Update all `"unlocked"` assertions" but the body correctly describes updating `activate()` signatures. Minor title/body mismatch.

STATUS: GREEN
