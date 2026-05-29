# PET-10 Edge Cases Review — Round 1

**Spec:** `docs/specs/TODO/PET-10.spec.md`
**Brief:** `docs/briefs/PET-10-jwt-license-premium-wiring.md`
**Round:** 1

---

## Findings

### F-1 — `_DEFAULT_VALIDATOR` lazy init has benign thread-safety race (P2)

**Severity:** P2
**Section:** Design §1 — Module-level convenience

The `validate_license()` function uses a global `_DEFAULT_VALIDATOR` with lazy initialization. In a multi-threaded scenario, two threads could create separate `LicenseValidator` instances. This is functionally benign (the validator is stateless and idempotent) but worth noting.

---

### F-4 — `assert self._license_claims is not None` violates pipeline-never-throws (P1)

**Severity:** P1
**Section:** Design §3 — `_check_premium()`

The spec shows `assert self._license_claims is not None` in `_check_premium()` after checking `self._license_state == LicenseState.VALID`. If any bug or race causes `_license_claims` to be `None` while `_license_state` is `VALID`, this assertion will crash the pipeline with `AssertionError`.

The CLAUDE.md invariant states: "Pipeline never throws — all errors caught and returned in PipelineResult." Using `assert` here creates a crash path that violates this invariant.

**Fix:** Replace `assert` with a defensive guard:
```python
if self._license_claims is None:
    self._license_state = LicenseState.INVALID
    return False
```

---

### F-7 — No input length guard on JWT token (P2)

**Severity:** P2
**Section:** Design §1 — `validate()`

There's no length limit on the token string passed to `validate()`. A multi-megabyte string would be passed directly to `jwt.decode()`. PyJWT handles this gracefully (it parses the three base64 segments), but a length guard would be an inexpensive defense-in-depth measure.

---

### F-8 — Missing `public.pem` at runtime crashes Pipeline constructor (P1)

**Severity:** P1
**Section:** Design §1 — `LicenseValidator.__init__`

If `public.pem` is missing from the installed package (packaging error, stripped sdist, etc.), `LicenseValidator.__init__` will raise an exception. Since `Pipeline.__init__` creates a `LicenseValidator` unconditionally, this means even OSS-only users who never call `activate()` will get a crash on `Pipeline()` construction.

**Fix:** Wrap key loading in try/except. If the key can't be loaded, set a flag that makes `validate()` always return `(INVALID, None)`. This preserves OSS functionality when the key file is absent.

---

### F-9 — Env var whitespace-only edge case (P2)

**Severity:** P2
**Section:** Design §3 — env var auto-activation

The spec says `if env_key:` to gate auto-activation. A whitespace-only `PETASOS_LICENSE_KEY` like `" "` will pass this truthiness check and be sent to `validate()`. After stripping, it becomes an empty string, which will be rejected as `INVALID`. This is functionally correct (silent failure) but wasteful. Could add `if env_key and env_key.strip():`.

---

### F-10 — Tri-state is a breaking change; test plan doesn't enumerate assertion updates (P1)

**Severity:** P1
**Section:** Design §3, Test plan

The tri-state change from `"unlocked"`/`"locked"` to `"available"`/`"disabled"`/`"locked"` is a breaking change. Existing tests in `test_pipeline.py` and `test_premium_integration.py` assert `"unlocked"` in `result.premium_features`. The test plan item 33 only says "Update existing `pipeline.activate()` calls" but doesn't mention updating the `"unlocked"` → `"available"` assertions.

**Fix:** Expand test plan item 33 to explicitly call out `"unlocked"` → `"available"` assertion updates across all affected test files.

---

### F-11 — `test_guard.py` calls `activate()` with no args — not listed in scope (P1)

**Severity:** P1
**Section:** Scope → Files to change

Duplicate of correctness F-1. `tests/test_guard.py` has 10 `pipe.activate()` calls that will break with the new `activate(key)` signature. Not listed in scope or test plan.

---

### F-14 — Clock skew tolerance not applied to lazy expiry check (P2)

**Severity:** P2
**Section:** Design §3 — `_check_premium()`

The lazy expiry check in `_check_premium()` uses `self._license_claims.expiry <= datetime.now(tz=timezone.utc)` — a hard boundary. But the initial validation in `LicenseValidator.validate()` uses PyJWT's `leeway` parameter (30s clock skew). This means a token that was accepted as valid (within leeway) could be immediately rejected by the lazy check on the very next `_check_premium()` call if the real expiry was within the leeway window. Minor inconsistency.

---

### F-15 — CLAUDE.md says `petasos.activate(key)` but spec exports `validate_license(key)` (P2)

**Severity:** P2
**Section:** __init__.py exports

CLAUDE.md states: "`petasos.activate(key)` or `PETASOS_LICENSE_KEY` env var". The spec exports `validate_license` at module level but `activate` is an instance method on Pipeline, not a module-level function. This is a documentation inconsistency in CLAUDE.md that should be updated post-PET-10.

---

## Closure Table

| Finding | Status |
|---------|--------|
| F-1 | OPEN (P2 — advisory) |
| F-4 | OPEN |
| F-7 | OPEN (P2 — advisory) |
| F-8 | OPEN |
| F-9 | OPEN (P2 — advisory) |
| F-10 | OPEN |
| F-11 | OPEN (duplicate of correctness F-1) |
| F-14 | OPEN (P2 — advisory) |
| F-15 | OPEN (P2 — advisory) |

STATUS: RED P0=0 P1=3
