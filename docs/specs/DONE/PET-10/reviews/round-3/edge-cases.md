# PET-10 Edge Cases Review — Round 3

**Spec:** `docs/specs/TODO/PET-10.spec.md`
**Brief:** `docs/briefs/PET-10-jwt-license-premium-wiring.md`
**Round:** 3

---

## Closure of Round 2 Findings

| Finding | Status | Evidence |
|---------|--------|----------|
| R2/F-1 (P1) "locked"→"disabled" assertions | CLOSED | Test plan items 35-36 added |
| R2/F-2 (P1) _premium_active attribute removed | CLOSED | Test plan item 37 added |
| R2/F-3 (P1) test_pipeline.py 3 activate() calls | CLOSED | Test plan item 39 enumerates all 3 by name |
| R2/F-4 (P2) no shared test fixture | CLOSED | Test plan item 42 added |
| R2/F-5 (P2) missing claim validation | CLOSED | Deferred item 6 |
| R2/F-6 (P2) _DEFAULT_VALIDATOR singleton | CLOSED | Deferred item 7 |
| R2/F-7 (P3) non-string features claim | CLOSED | Deferred item 8 |
| R2/F-8 (P2) timezone-naive expiry | CLOSED | Design §1 specifies `datetime.fromtimestamp(exp, tz=timezone.utc)` |

## Findings

### F-1 — `_build_premium_features` doesn't call lazy expiry check (P2)

`_build_premium_features()` checks `self._license_state == VALID` but doesn't call `_check_premium()` which does the lazy expiry. Functionally safe because `inspect()` calls `_check_premium()` before `_build_premium_features()`, but the manifest method is not independently safe. Advisory — call ordering is documented in Design §3.

### F-2 — Profiles `__init__.py` line 110 still says "locked" (P2)

`profiles/__init__.py` is marked "verify only" in scope, but its `_default_premium_features()` returns `"locked"` for all features. After PET-10, this should still be `"locked"` (no license = locked). Verify-only is correct — no change needed.

### F-3 — activate() count discrepancy (P2)

Same as correctness F-1. The scope table count of 37 may not match the actual file. Implementer will grep regardless.

### F-4 — Profile `_default_premium_features` returns dict not MappingProxyType (P3)

`profiles/__init__.py` returns a plain dict from `_default_premium_features()`. The hardening pass says `_build_premium_features()` returns `MappingProxyType` but doesn't mention the profile helper. Minor — profile helper is internal and the pipeline wraps the result.

STATUS: GREEN
