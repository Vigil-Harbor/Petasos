# PET-39 — License Hardening (LIC-04, LIC-07, LIC-08, LIC-09)

**Tickets:** PET-39 (LIC-04), PET-40 (LIC-07), PET-41 (LIC-08), PET-42 (LIC-09)
**Priority:** Medium
**OWASP:** ASI07 — Insufficient threat-detection coverage
**Parent:** PET-14 · **Blocks:** PET-12 (release)

---

## Goal

Harden `LicenseValidator` against four red-team findings: key swap via unverified `public.pem` (LIC-04), timestamp overflow crashing claims construction (LIC-07), forged tier strings bypassing post-decode validation (LIC-08), and weaponized clock skew neutralizing JWT expiry (LIC-09). All four fixes are independent, confined to `petasos/premium/license.py`, and follow the fail-secure principle — every malformed or suspicious input results in `(LicenseState.INVALID, None)`.

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/premium/license.py` | Add key fingerprint validation (LIC-04), try/except around claims construction (LIC-07), tier allowlist check (LIC-08), clock skew cap (LIC-09), `valid_tiers` constructor parameter |
| `tests/test_license.py` | Update `test_default_tier_when_missing` to expect `INVALID` (tier `None` is no longer valid with allowlist) |

### New files

| File | Purpose |
|------|---------|
| `tests/adversarial/license/test_license_hardening.py` | 12+ regression tests covering all four findings |

### Files unchanged

- `petasos/premium/_keys/public.pem` — the key itself is unchanged; only the validator's integrity check of it changes.
- `petasos/premium/_keys/__init__.py` — empty package marker, untouched.
- `petasos/pipeline.py` — no pipeline changes.
- `petasos/config.py` — no config changes.
- `tests/conftest.py` — `_make_token()` helper is sufficient for most new tests. Test #12 also imports `_PRIVATE_KEY` for direct `jwt.encode` (to construct a JWT with no `tier` key). No modifications needed.
- `tests/adversarial/license/test_jwt_attacks.py` — existing adversarial tests remain unchanged.

## Decisions

### Decision 1: Hash LF-normalized PEM bytes, not decoded DER

The fingerprint is `hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()` where `raw` is the file content of `public.pem`. Normalizing line endings before hashing ensures the fingerprint is platform-independent — on Windows with `core.autocrlf=true`, the file is checked out with CRLF (116 bytes), while on Linux/macOS it's LF (113 bytes). Without normalization, the hash differs across platforms and the fingerprint check would fail on non-Windows installs. Hashing raw bytes (not DER-decoded key material) is simpler and still effective — any change to the file beyond line-ending normalization changes the hash. The canonical LF-normalized fingerprint is `009e2106b18ccb31ac1d74da4db9a9dc35097cb378e1f84688ff1b350b1bfb92`.

### Decision 2: Tier allowlist includes `"standard"` as a valid tier

The brief specifies `{"free", "pro", "enterprise"}`. The spec adds `"standard"` because the existing code defaults to `"standard"` when `tier` is absent from the JWT payload (`str(payload.get("tier", "standard"))` at L68). Without `"standard"` in the allowlist, a legitimate token that simply omits the `tier` claim would be rejected. The allowlist becomes `{"free", "standard", "pro", "enterprise"}`.

### Decision 3: Tier check operates on the raw payload value, not the stringified default

The tier allowlist check runs against `str(payload.get("tier", "standard"))` — the same expression used to populate `LicenseClaims.tier`. This means:
- Missing `tier` claim → defaults to `"standard"` → passes (in allowlist).
- `tier: null` in JWT → `str(None)` = `"None"` → fails (not in allowlist). This is a deliberate behavioral change — the existing `test_default_tier_when_missing` test (which asserts `tier == "None"` is valid) will be updated to expect `INVALID`.
- `tier: "superadmin"` → fails.

### Decision 4: Key pinning vs. key embedding — fingerprint wins

Embedding the key as a Python bytes literal would eliminate the file I/O surface entirely, but makes rotation harder (requires a code change, not just a file swap + fingerprint update). Pinning the fingerprint keeps the `.pem` file as the single source of truth for key material while adding tamper detection. Consistent with the brief's recommendation.

### Decision 5: Clock skew cap at 300 is a hard constructor error, not a silent clamp

`ValueError` is the right signal — it's a programmer error to pass `1e9` as clock skew. Silent clamping would hide misconfigurations. The 300-second cap is generous for real-world clock drift (NTP-synced hosts drift < 1s; misconfigured hosts rarely exceed 60s).

### Decision 6: Fingerprint mismatch sets `_key = None` (fail-secure), does not raise

Consistent with the existing pattern: key loading failures (missing file, decode error) silently set `_key = None`, and `validate()` returns `(INVALID, None)` on the `_key is None` guard at L47-48. Raising an exception from `__init__` would change the construction contract and break existing callers who expect `LicenseValidator()` to always succeed.

## Design

### 1. Clock skew cap — LIC-09 (L34–35)

Add `import math` at the top. Add validation at the top of `__init__`, before `self._clock_skew` assignment:

```python
def __init__(
    self,
    *,
    clock_skew_seconds: float = 30.0,
    valid_tiers: frozenset[str] | None = None,
) -> None:
    if not math.isfinite(clock_skew_seconds) or clock_skew_seconds < 0:
        raise ValueError(f"clock_skew_seconds must be a finite non-negative number, got {clock_skew_seconds}")
    if clock_skew_seconds > 300:
        raise ValueError(
            f"clock_skew_seconds must be <= 300, got {clock_skew_seconds}"
        )
    self._clock_skew = timedelta(seconds=clock_skew_seconds)
    if valid_tiers is not None and len(valid_tiers) == 0:
        raise ValueError("valid_tiers must not be empty")
    self._valid_tiers = valid_tiers if valid_tiers is not None else _VALID_TIERS
```

The `math.isfinite()` check catches NaN (which bypasses `< 0` and `> 300` due to IEEE 754 comparison semantics) and `float('inf')`. The negative check catches `timedelta(seconds=-1)` which would widen the acceptance window. The empty `valid_tiers` guard prevents silent misconfiguration where all tokens are rejected.

### 2. Key fingerprint validation — LIC-04 (L36–44)

Add `import hashlib` at the top. Define the pinned fingerprint as a module-level constant (LF-normalized):

```python
_EXPECTED_KEY_FINGERPRINT = (
    "009e2106b18ccb31ac1d74da4db9a9dc35097cb378e1f84688ff1b350b1bfb92"
)
```

In `__init__`, after reading the key bytes, normalize line endings and verify the fingerprint before loading the key:

```python
try:
    pkg = importlib.resources.files("petasos.premium._keys")
    raw = pkg.joinpath("public.pem").read_bytes()
    normalized = raw.replace(b"\r\n", b"\n")
    if hashlib.sha256(normalized).hexdigest() != _EXPECTED_KEY_FINGERPRINT:
        self._key = None
    else:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        self._key = load_pem_public_key(raw)
except Exception:
    self._key = None
```

Line-ending normalization (`\r\n` → `\n`) ensures the fingerprint is platform-independent — the same hash on Windows (CRLF checkout) and Linux/macOS (LF checkout). The original `raw` bytes are passed to `load_pem_public_key` since the cryptography library handles both line endings. The fingerprint check runs before `load_pem_public_key` — if the hash mismatches, we don't even attempt to parse the attacker-controlled PEM file.

### 3. Tier allowlist — LIC-08 (L67–74)

Add module-level constant:

```python
_VALID_TIERS: frozenset[str] = frozenset({"free", "standard", "pro", "enterprise"})
```

In `validate()`, after successful JWT decode and before claims construction, check the tier:

```python
tier_str = str(payload.get("tier", "standard"))
if tier_str not in self._valid_tiers:
    return (LicenseState.INVALID, None)
```

This check uses `self._valid_tiers` (set from constructor parameter or default) and operates on the same expression used to populate `LicenseClaims.tier`, ensuring consistency.

### 4. Claims construction overflow guard — LIC-07 (L67–73)

Wrap the `LicenseClaims` construction in a try/except:

```python
try:
    claims = LicenseClaims(
        tier=tier_str,
        customer_id=str(payload.get("customer_id", "")),
        expiry=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        issued_at=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
        features=frozenset(payload.get("features", [])),
    )
except (OverflowError, OSError, ValueError, TypeError):
    return (LicenseState.INVALID, None)
```

Note: `tier_str` is reused from the allowlist check (Design §3), eliminating the duplicate `str(payload.get(...))` call. The `tier=tier_str` assignment replaces the inline expression.

`OverflowError` covers timestamps like `10**18`. `OSError` covers platform-specific timestamp range violations. `ValueError` covers edge cases like negative timestamps on some platforms. `TypeError` covers malformed `features` payloads — a JWT with `features: 42` (integer instead of array) passes `jwt.decode` but `frozenset(42)` raises `TypeError`.

## Test plan

### New tests — `tests/adversarial/license/test_license_hardening.py`

| # | Test | Finding | Asserts |
|---|------|---------|---------|
| 1 | `test_swapped_key_returns_invalid` | LIC-04 | Monkeypatch `importlib.resources.files` to return a different Ed25519 public key; `validate()` returns `INVALID` |
| 2 | `test_fingerprint_mismatch_nullifies_key` | LIC-04 | Monkeypatch to return key bytes with wrong fingerprint; verify `validator._key is None` |
| 3 | `test_correct_fingerprint_loads_key` | LIC-04 | Default construction (no monkeypatch); verify `validator._key is not None` |
| 4 | `test_exp_overflow_returns_invalid` | LIC-07 | Create token with `exp=10**18` (overflows `datetime.fromtimestamp`); `validate()` returns `INVALID`, no exception |
| 5 | `test_exp_infinity_returns_invalid` | LIC-07 | Create token with `extra_claims={"exp": float("inf")}`; `validate()` returns `INVALID`, no exception. Maps the brief's `exp=1e999` criterion (Python evaluates `1e999` as `inf`). |
| 6 | `test_iat_overflow_returns_invalid` | LIC-07 | Create token with `iat=10**18`; `validate()` returns `INVALID` |
| 7 | `test_malformed_features_returns_invalid` | LIC-07 | Create token with `extra_claims={"features": 42}` (integer, not array); `validate()` returns `INVALID` (catches `TypeError` from `frozenset(42)`) |
| 8 | `test_unknown_tier_returns_invalid` | LIC-08 | Create token with `tier="superadmin"`; `validate()` returns `INVALID` |
| 9 | `test_null_tier_returns_invalid` | LIC-08 | Create token with `extra_claims={"tier": None}` (JSON null); `validate()` returns `INVALID` |
| 10 | `test_empty_tier_returns_invalid` | LIC-08 | Create token with `tier=""`; `validate()` returns `INVALID` |
| 11 | `test_valid_tiers_accepted` | LIC-08 | Parameterized: `"free"`, `"standard"`, `"pro"`, `"enterprise"` all return `VALID` |
| 12 | `test_missing_tier_defaults_to_standard` | LIC-08 | Create token via direct `jwt.encode` with no `tier` key; `validate()` returns `VALID` with `claims.tier == "standard"`. Exercises Decision 2. |
| 13 | `test_custom_valid_tiers` | LIC-08 | Construct `LicenseValidator(valid_tiers=frozenset({"custom"}))` with a `tier="custom"` token; returns `VALID`. `tier="pro"` returns `INVALID` (not in custom set). |
| 14 | `test_empty_valid_tiers_rejected` | LIC-08 | `LicenseValidator(valid_tiers=frozenset())` raises `ValueError` |
| 15 | `test_clock_skew_cap_exceeded` | LIC-09 | `LicenseValidator(clock_skew_seconds=301)` raises `ValueError` |
| 16 | `test_clock_skew_cap_boundary` | LIC-09 | `LicenseValidator(clock_skew_seconds=300)` succeeds |
| 17 | `test_clock_skew_negative` | LIC-09 | `LicenseValidator(clock_skew_seconds=-1)` raises `ValueError` |
| 18 | `test_clock_skew_nan` | LIC-09 | `LicenseValidator(clock_skew_seconds=float("nan"))` raises `ValueError` |
| 19 | `test_clock_skew_extreme` | LIC-09 | `LicenseValidator(clock_skew_seconds=1e9)` raises `ValueError` |

### Existing test updates

| File | Test | Change |
|------|------|--------|
| `tests/test_license.py` | `test_default_tier_when_missing` (L95–101) | Update to expect `LicenseState.INVALID` and `claims is None`. Rationale: `tier=None` in JWT is now rejected by allowlist (Decision 3). |

### Existing test verification

| File | Impact |
|------|--------|
| `tests/test_license.py` | All other tests must remain green. Tests using `tier="pro"` and `tier="enterprise"` pass (both in allowlist). |
| `tests/adversarial/license/test_jwt_attacks.py` | No changes — existing adversarial tests are independent (they test algorithm restrictions and garbage tokens, not claims validation). |

## Test command

```
python -m pytest tests/test_license.py tests/adversarial/license/ -v && ruff check . && ruff format --check . && mypy --strict petasos/premium/license.py tests/adversarial/license/test_license_hardening.py
```

## Done when

- [ ] Replacing `public.pem` with a different key → all `validate()` calls return `INVALID`
- [ ] Key fingerprint is platform-independent (LF-normalized before hashing)
- [ ] JWT with `exp=10**18` → `INVALID`, no exception raised
- [ ] JWT with `exp=float("inf")` → `INVALID`, no exception raised
- [ ] JWT with malformed `features` (integer, not array) → `INVALID`, no exception
- [ ] JWT with `tier="superadmin"` → `INVALID`
- [ ] JWT with `tier=None` (JSON null) → `INVALID`
- [ ] JWT with `tier=""` (empty string) → `INVALID`
- [ ] JWT with missing `tier` key → `VALID` with `claims.tier == "standard"`
- [ ] `LicenseValidator(clock_skew_seconds=1e9)` raises `ValueError`
- [ ] `LicenseValidator(clock_skew_seconds=300)` is accepted (boundary)
- [ ] `LicenseValidator(clock_skew_seconds=-1)` raises `ValueError`
- [ ] `LicenseValidator(clock_skew_seconds=float("nan"))` raises `ValueError`
- [ ] `LicenseValidator(valid_tiers=frozenset())` raises `ValueError`
- [ ] `valid_tiers` constructor parameter overrides default tier set
- [ ] ≥ 19 tests in `tests/adversarial/license/test_license_hardening.py`
- [ ] `test_default_tier_when_missing` updated to expect `INVALID`
- [ ] `mypy --strict` clean on `license.py` and new test file (CI runs whole-project `mypy --strict .`)
- [ ] Existing license tests still pass (except updated test)
- [ ] `ruff check .` and `ruff format --check .` clean

## Out of scope

- Key rotation mechanism (future PET-12 scope: document rotation procedure).
- Online license validation / license server.
- JWT claim schema versioning.
- Embedding key material as a Python bytes literal (Decision 4: fingerprint pinning is sufficient).
- Validating `features` claim contents (list membership check) — features are consumed downstream, not security-critical at the license layer.
- `LicenseClaims` field immutability hardening — already `frozen=True` dataclass; `object.__setattr__` bypass is CFG-01 scope (Brief 3).

## Deferred (P2+)

- **`_DEFAULT_VALIDATOR` module singleton is mutable (P3):** `_DEFAULT_VALIDATOR` at L77 can be reassigned via `module.__dict__` or `object.__setattr__`. A `Final` annotation would add static protection. Deferred — same class of attack as CFG-04 (module-level constant mutability), addressed in Brief 3.
- **`validate_license()` does not accept `valid_tiers` (P3):** The convenience function constructs `LicenseValidator()` with no arguments. Callers needing custom tiers must construct `LicenseValidator` directly. Acceptable for the hardening scope; API ergonomics is a separate concern.
- **`features` claim validation (P4):** The `features` frozenset is populated from the JWT without checking that each feature string is recognized. Unknown features pass through silently. Low risk — features are checked downstream at the premium-module enablement layer, not used for security decisions at the license layer.
- **Thread-safety of `_DEFAULT_VALIDATOR` singleton (P3):** Two threads calling `validate_license()` simultaneously when the singleton is `None` may both construct validators. Benign race — `LicenseValidator.__init__` is idempotent. Pre-existing condition not worsened by this spec.
