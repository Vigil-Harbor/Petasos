# PET-39 — License Hardening (LIC-04, LIC-07, LIC-08, LIC-09)

**Plane items:** PET-39 (LIC-04), PET-40 (LIC-07), PET-41 (LIC-08), PET-42 (LIC-09)
**Files touched:** `petasos/premium/license.py`, `tests/test_license.py`, `tests/adversarial/license/`
**Priority:** medium (LIC-04, LIC-07, LIC-09); low (LIC-08)
**Parent:** PET-14 (red-team security review)
**Blocks:** PET-12 (release)

---

## Findings

| ID | Severity | Attack | Current behavior | Remediation |
|----|----------|--------|------------------|-------------|
| LIC-04 | medium | Replace bundled `public.pem` with attacker key | No integrity check on loaded public key; local file swap enables forged JWTs | Pin key fingerprint (SHA-256 of public key bytes) as a constant in code; validate at load |
| LIC-07 | medium | JWT with `exp=1e999` | `datetime.fromtimestamp()` after decode can raise `OverflowError`/`OSError` on extreme timestamps | Wrap claims-build block (`datetime.fromtimestamp(payload["exp"])`) in try/except; treat as INVALID |
| LIC-08 | low | Forged `tier` string (e.g., `"tier": "superadmin"`) in signed token | No `tier` allowlist post-decode; unknown tiers pass through | Add `_VALID_TIERS = frozenset({"free", "pro", "enterprise"})` allowlist; reject unknown tiers as INVALID |
| LIC-09 | medium | `LicenseValidator(clock_skew_seconds=1e9)` — ~31 years leeway | No upper bound on `clock_skew_seconds`; huge values neutralize `exp` | Cap `clock_skew_seconds` at 300 (5 min) in `__init__`; raise `ValueError` if exceeded |

## Approach

All four fixes are in `license.py` and are independent:

1. **LIC-04 (key pinning):** Compute `hashlib.sha256(key_bytes).hexdigest()` at module level as `_EXPECTED_KEY_FINGERPRINT`. In `__init__`, after loading key bytes, compare against the pinned fingerprint. Mismatch -> `_key = None` (fail-secure, same as missing key).

2. **LIC-07 (exp overflow):** The claims-build block (lines 67-73) calls `datetime.fromtimestamp(payload["exp"])`. Wrap in try/except `(OverflowError, OSError, ValueError)` -> return `(INVALID, None)`.

3. **LIC-08 (tier allowlist):** After successful decode, check `payload.get("tier") in _VALID_TIERS`. Unknown tier -> `(INVALID, None)`. The allowlist must be extensible via a constructor parameter for forward compatibility.

4. **LIC-09 (skew cap):** In `__init__`, add `if clock_skew_seconds > 300: raise ValueError(...)`. The 300-second cap is generous for clock drift but prevents neutralization.

## Decisions carried forward

- **Key pinning vs. key embedding:** Pinning the fingerprint (not the key itself) means the `.pem` file is still a file on disk, but its contents are validated. Alternative: embed the key as a Python bytes literal. Decision: pin fingerprint -- it's simpler, and the key file is useful for tooling and rotation documentation.
- **Tier allowlist extensibility:** Accept an optional `valid_tiers: frozenset[str] | None` constructor parameter. If `None`, use the built-in set. This supports custom tiers without code changes.
- **Clock skew 300s cap:** NTP-synced systems rarely drift more than a few seconds; 300s covers misconfigured hosts. If a customer legitimately needs more, they can subclass -- but the default protects against weaponized leeway.

## Done when

- [ ] Replacing `public.pem` with a different key -> all `validate()` calls return `INVALID`
- [ ] JWT with `exp=1e999` -> `INVALID`, no exception
- [ ] JWT with `tier="superadmin"` -> `INVALID`
- [ ] `LicenseValidator(clock_skew_seconds=1e9)` raises `ValueError`
- [ ] `LicenseValidator(clock_skew_seconds=300)` is accepted (boundary)
- [ ] >= 12 tests (3 per finding)
- [ ] `mypy --strict` clean
- [ ] Existing license tests still pass

## Out of scope

- Key rotation mechanism (future PET-12 scope: document rotation procedure)
- Online license validation / license server
- JWT claim schema versioning
