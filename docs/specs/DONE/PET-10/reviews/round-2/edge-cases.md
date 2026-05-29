# PET-10 Edge Cases Review — Round 2

**Spec:** `docs/specs/TODO/PET-10.spec.md`
**Brief:** `docs/briefs/PET-10-jwt-license-premium-wiring.md`
**Round:** 2

---

## Closure of Round 1 Findings

| Finding | Status | Evidence |
|---------|--------|----------|
| R1/F-1 (P2) thread-safety race | CLOSED | Deferred item 1 |
| R1/F-4 (P1) assert in _check_premium | CLOSED | Design §3 defensive guard |
| R1/F-7 (P2) no input length guard | CLOSED | Deferred item 2 |
| R1/F-8 (P1) missing public.pem crash | CLOSED | Design §1 resilient key loading |
| R1/F-9 (P2) whitespace-only env var | CLOSED | Deferred item 3 |
| R1/F-10 (P1) tri-state assertion updates | PARTIAL | Items 34/39 cover "unlocked"→"available" but miss "locked"→"disabled" |
| R1/F-11 (P1) test_guard.py activate() | CLOSED | Scope table + test plan items 35-36 |
| R1/F-14 (P2) clock skew lazy check | CLOSED | Deferred item 4 |
| R1/F-15 (P2) CLAUDE.md divergence | CLOSED | Deferred item 5 |

## Findings

### F-1 — Tri-state `"locked"` → `"disabled"` assertions not in test plan (P1)

**Where:** test plan items 33-34, 39
**Edge case:** licensed + feature config disabled = `"disabled"` (was `"locked"`)

Existing tests assert `"locked"` when premium is active but a feature is toggled off:
- `test_premium_integration.py:343` — `tool_guard_enabled=False`, premium active, asserts `"locked"`
- `test_premium_integration.py:460-461` — `audit_enabled=False, alert_enabled=False`, premium active, asserts `"locked"`

Under tri-state, these should assert `"disabled"`. Test plan only covers `"unlocked"` → `"available"`, not `"locked"` → `"disabled"` for the licensed-but-feature-off case.

**Fix:** Add test plan item: "Update `"locked"` assertions to `"disabled"` in tests where premium is active and feature config is `False`."

### F-2 — `test_premium_integration.py` asserts `pipe._premium_active` directly — attribute removed (P1)

**Where:** spec scope table line 34
**Edge case:** Internal attribute rename/removal breaks direct attribute access

`test_premium_integration.py` lines 180, 182, 188 assert `pipe._premium_active is False` and `pipe._premium_active is True`. PET-10 removes `_premium_active` entirely (replaced by `_license_state`). These assertions will raise `AttributeError`. Test plan items 33-34 only mention updating `activate()` calls and `"unlocked"` assertions — they don't cover `_premium_active` attribute assertions.

**Fix:** Add test plan item: "Update `TestActivateDeactivate` in `test_premium_integration.py`: replace `pipe._premium_active` assertions with `pipe._license_state` comparisons."

### F-3 — `test_pipeline.py` has 3 no-arg `activate()` calls not enumerated (P1)

**Where:** spec scope table line 33
**Edge case:** activate() signature change breaks additional test_pipeline.py tests

`test_pipeline.py` lines 729, 741, 755 call `p.activate()` with no arguments (`test_inspect_profile_override_dict`, `test_inspect_profile_override_string`, `test_is_premium_active_public`). Scope entry says "Update activate() → activate(valid_key)" generically but doesn't enumerate these specific tests.

**Fix:** Add test plan item: "Update 3 existing `p.activate()` calls in `test_pipeline.py` to `p.activate(valid_key)`."

### F-4 — No shared test fixture pattern for valid JWT key (P2)

37 `activate()` calls across test_premium_integration.py + 10 in test_guard.py + 3 in test_pipeline.py all need a `valid_key`. Spec doesn't describe how to generate test JWTs or a shared fixture pattern.

### F-5 — Missing custom claim validation in LicenseClaims construction (P2)

JWT with valid signature + exp/iat but missing `tier`/`customer_id` hits catch-all as INVALID. Functionally correct but indistinguishable from forged key.

### F-6 — `_DEFAULT_VALIDATOR` singleton leaks across test isolation boundaries (P2)

Module-level singleton retains state between tests. Tests using `validate_license()` should reset it in teardown.

### F-7 — Non-string elements in JWT `features` claim (P3)

`frozenset(payload["features"])` silently accepts non-string hashable types.

### F-8 — Timezone-naive `LicenseClaims.expiry` vs timezone-aware comparison (P2)

Spec should specify `datetime.fromtimestamp(payload['exp'], tz=timezone.utc)` to ensure timezone-aware datetimes.

STATUS: RED P0=0 P1=3 P2=4 P3=1 P4=0
