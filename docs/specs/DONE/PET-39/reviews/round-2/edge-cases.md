# Edge-Cases Review -- round 2

## Closure of round 1 findings
All 9 round 1 findings CLOSED with evidence.

## Findings

### F-1: Test 5 does not exercise claims-construction guard
**Severity:** P3
Same as correctness F-1. `float("inf")` is caught at jwt.decode layer, not the new try/except. Test is still valuable as contract test.

### F-2: features claim as string silently produces character-level frozenset
**Severity:** P3
`"features": "audit"` → `frozenset({'a','d','i','t','u'})`. Silent data corruption. Explicitly deferred in spec (features validation out of scope).

### F-3: No test for features=null (JSON null)
**Severity:** P3
`features: null` → `frozenset(None)` → TypeError. Caught by new except clause. No dedicated test, but same code path as Test #7 (`features: 42`).

### F-4: Spec claims conftest unchanged but Test 12 needs _PRIVATE_KEY
**Severity:** P2
Test #12 uses direct `jwt.encode` which requires `_PRIVATE_KEY` import. The "Files unchanged" note says `_make_token()` is sufficient for all new tests — this is inaccurate.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 3 | P4: 0

STATUS: GREEN
