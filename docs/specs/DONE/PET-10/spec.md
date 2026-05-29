# PET-10: JWT License Validation + Premium Wiring

**Ticket:** PET-10
**Phase:** 7a (Integration + Hardening)
**Brief:** `docs/briefs/PET-10-jwt-license-premium-wiring.md`
**Blocked by:** PET-7 (shipped), PET-8 (shipped), PET-9 (shipped)
**Blocks:** PET-11 (integration testing)

---

## Goal

Replace the boolean `_premium_active` scaffold with real JWT license validation using Ed25519 signatures via PyJWT. After this change, the public API is `pipeline.activate(key)` or `PETASOS_LICENSE_KEY` env var, JWT validated locally with a bundled public key, premium stages run on the next `inspect()` call. No pipeline reconstruction, no network. Additionally, perform a security hardening pass to enforce immutability across all exported types.

---

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/premium/license.py` | **New.** `LicenseValidator`, `LicenseClaims`, `LicenseState`, `validate_license()` |
| `petasos/premium/_keys/public.pem` | **New.** Test Ed25519 public key (swapped at release) |
| `petasos/premium/_keys/__init__.py` | **New.** Empty `__init__.py` for `importlib.resources` package discovery |
| `petasos/pipeline.py` | Refactor `activate(key)`, `deactivate()`, `_check_premium()`, `_build_premium_features()` tri-state; env var auto-activation in `__init__` |
| `petasos/__init__.py` | Export `LicenseClaims`, `LicenseState`, `validate_license` |
| `petasos/premium/profiles/__init__.py` | Verify only — `ResolvedProfile` is frozen with all-immutable fields; no code changes needed |
| `petasos/premium/__init__.py` | Re-export `LicenseClaims`, `LicenseState`, `LicenseValidator`, `validate_license` from `license.py` |
| `pyproject.toml` | Add `pyjwt[crypto]>=2.8,<3` to base `dependencies`; merge `jwt` into existing mypy overrides block |
| `tests/test_license.py` | **New.** License validation tests |
| `tests/test_hardening.py` | **New.** Frozen export + defensive copy mutation tests |
| `tests/test_pipeline.py` | Update `activate()` → `activate(valid_key)` and `"unlocked"` → `"available"` assertions |
| `tests/test_premium_integration.py` | Update `activate()` → `activate(valid_key)` and `"unlocked"` → `"available"` assertions |
| `tests/test_guard.py` | Update 10 `pipe.activate()` calls to `pipe.activate(valid_key)` |

### Files to leave alone

- `petasos/config.py` — license key is runtime state, not config
- `petasos/premium/audit.py` — no changes needed
- `petasos/premium/alerting.py` — no changes needed
- `petasos/premium/frequency.py` — no changes needed
- `petasos/premium/escalation.py` — no changes needed
- `petasos/premium/guard.py` — uses `pipeline.is_premium_active()` which delegates to `_check_premium()`; no direct changes needed
- `petasos/scanners/*` — no changes needed

---

## Decisions

### Decision: Ed25519, not RS256

Ed25519 keys are 32 bytes vs 2048+ bits for RSA. Faster verification, no padding oracle attacks. PyJWT supports Ed25519 via the `cryptography` backend. The brief mandates this choice.

### Decision: Algorithm restriction to EdDSA only

`jwt.decode()` will pass `algorithms=["EdDSA"]` exclusively. This prevents algorithm confusion attacks where an attacker supplies `alg: "none"` (signature bypass) or `alg: "HS256"` (public-key-as-HMAC-secret attack). Defense in depth.

### Decision: Lazy expiry check, not background timer

No threads, no timers, no lifecycle complexity. Expiry is detected on the next `_check_premium()` call. When `exp < now`, `_license_state` flips to `EXPIRED` and premium gates close. Good enough for a library.

### Decision: No module-level singleton pipeline

`petasos.validate_license(key)` is a stateless check that returns `LicenseState`. `pipeline.activate(key)` is instance-scoped activation. Libraries shouldn't own singletons; global state couples pipeline lifecycle to import state.

### Decision: PyJWT as base dependency

PyJWT with `cryptography` backend is needed for Ed25519 verification. Added to base `dependencies` in `pyproject.toml` rather than as an optional extra. The premium path is a core feature, not an optional integration. `cryptography` ships binary wheels for all platforms — no build-from-source risk.

### Decision: Silent env var failure

If `PETASOS_LICENSE_KEY` is set to an invalid value, `Pipeline.__init__` catches the failure silently and continues in OSS-only mode. The env var is a convenience, not a requirement — garbage input should never crash the consuming app.

### Decision: Tri-state manifest replaces binary

`_build_premium_features()` currently returns `"unlocked"` / `"locked"`. PET-10 changes to `"available"` / `"disabled"` / `"locked"`. This is a breaking change from PET-7/8/9, acceptable since nothing is released (pre-alpha). The tri-state lets frontends distinguish between "premium active + feature on" vs "premium active + feature toggled off" vs "no license".

### Decision: Whitespace/invisible-char stripping on JWT input

Per the brief's platform consideration (§13 — credential sanitization in Hermes Desktop): `LicenseValidator.validate()` strips leading/trailing whitespace and common invisible Unicode characters (BOM, zero-width joiners) before decoding. JWTs copy-pasted from PDFs or web UIs may contain these.

---

## Design

### 1. LicenseValidator (`petasos/premium/license.py`)

**Types:**

```python
class LicenseState(enum.Enum):
    INACTIVE = "inactive"
    VALID = "valid"
    EXPIRED = "expired"
    INVALID = "invalid"

@dataclass(frozen=True)
class LicenseClaims:
    tier: str                    # "pro" | "team" | "enterprise"
    customer_id: str
    expiry: datetime             # from JWT `exp` claim
    issued_at: datetime          # from JWT `iat` claim
    features: frozenset[str]     # entitled feature names
```

**Validator class:**

```python
class LicenseValidator:
    def __init__(self, *, clock_skew_seconds: float = 30.0) -> None:
        # Load public key from petasos/premium/_keys/public.pem
        # via importlib.resources (same pattern as profiles)
        # If key loading fails (missing file, packaging error, corrupt key):
        #   set self._key = None (validate() will always return INVALID)
        #   — preserves OSS functionality when key file is absent

    def validate(self, token: str) -> tuple[LicenseState, LicenseClaims | None]:
        # 0. If self._key is None: return (INVALID, None) immediately
        # 1. Strip whitespace + invisible chars (BOM, ZWJ, ZWNJ, zero-width space)
        # 2. jwt.decode(token, key, algorithms=["EdDSA"],
        #              options={"require": ["exp", "iat"]},
        #              leeway=timedelta(seconds=self._clock_skew))
        # 3. On success: extract claims. Convert exp/iat to timezone-aware:
        #    datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        #    Return (VALID, LicenseClaims(...))
        # 4. On jwt.ExpiredSignatureError: return (EXPIRED, None)
        # 5. On any other exception: return (INVALID, None)
```

Key behaviors:
- **Never throws.** All exceptions caught internally, returned as `(INVALID, None)`. Constructor also never throws — key loading failure is handled gracefully.
- **Resilient key loading.** If `public.pem` is missing at runtime (packaging error, stripped sdist), the validator degrades to always returning `(INVALID, None)` rather than crashing. This is critical because `Pipeline.__init__` creates a `LicenseValidator` unconditionally — OSS-only users who never call `activate()` must not get a constructor crash.
- Algorithm restriction enforced by PyJWT's `algorithms` parameter — tokens with `alg: "none"`, `alg: "HS256"`, or any non-EdDSA algorithm are rejected with `InvalidAlgorithmError`.
- Public key loaded once at `LicenseValidator.__init__` via `importlib.resources.files("petasos.premium._keys")`.
- Clock skew tolerance: 30 seconds default, configurable via constructor.

**Module-level convenience:**

```python
_DEFAULT_VALIDATOR: LicenseValidator | None = None

def validate_license(token: str) -> LicenseState:
    global _DEFAULT_VALIDATOR
    if _DEFAULT_VALIDATOR is None:
        _DEFAULT_VALIDATOR = LicenseValidator()
    state, _ = _DEFAULT_VALIDATOR.validate(token)
    return state
```

This is stateless (no pipeline coupling). Lazily instantiated to avoid loading the public key at import time if license features are never used.

### 2. Key bundling

- `petasos/premium/_keys/public.pem` — Ed25519 public key in PEM format.
- `petasos/premium/_keys/__init__.py` — empty, makes it a package for `importlib.resources`.
- For testing: generate a test keypair. The test private key lives in `tests/fixtures/test_private.pem` — never shipped in the package.
- v1 ships with one key. Future versions add `kid` header rotation (out of scope for PET-10).

### 3. Hot-unlock wiring in Pipeline

**`Pipeline.__init__` changes:**

```python
def __init__(self, ...) -> None:
    # ... existing setup ...
    self._license_validator = LicenseValidator()
    self._license_state = LicenseState.INACTIVE
    self._license_claims: LicenseClaims | None = None

    # Env var auto-activation (silent failure)
    env_key = os.environ.get("PETASOS_LICENSE_KEY")
    if env_key:
        self.activate(env_key)  # return value intentionally discarded
```

**`Pipeline.activate(key: str) -> LicenseState`:**

```python
def activate(self, key: str) -> LicenseState:
    state, claims = self._license_validator.validate(key)
    self._license_state = state
    self._license_claims = claims if state == LicenseState.VALID else None
    return state
```

Breaking change: `activate()` now requires a `key` argument and returns `LicenseState`. The old no-arg `activate()` from PET-7 is removed. Acceptable — pre-alpha, no public consumers.

**`Pipeline.deactivate()` unchanged behavior:**

```python
def deactivate(self) -> None:
    self._license_state = LicenseState.INACTIVE
    self._license_claims = None
```

Session state (frequency scores, escalation tiers) is preserved. Only the license gate changes.

**`Pipeline._check_premium(feature_name)` refactored:**

```python
def _check_premium(self, feature_name: str) -> bool:
    if self._license_state != LicenseState.VALID:
        return False

    # Defensive guard — self-heal if state/claims are inconsistent
    if self._license_claims is None:
        self._license_state = LicenseState.INVALID
        return False

    # Lazy expiry check
    if self._license_claims.expiry <= datetime.now(tz=timezone.utc):
        self._license_state = LicenseState.EXPIRED
        self._license_claims = None
        return False

    # Per-feature config gate (existing logic)
    attr = self._FEATURE_GATES.get(feature_name)
    if attr is not None:
        return bool(getattr(self._config, attr, True))
    return True
```

The lazy expiry check runs on every premium gate evaluation. No polling, no timers. When expiry is detected, state flips to `EXPIRED` and all premium features deactivate. OSS stages continue running — pipeline never crashes due to license state.

**`Pipeline._build_premium_features()` tri-state:**

```python
def _build_premium_features(self) -> MappingProxyType[str, str]:
    licensed = self._license_state == LicenseState.VALID

    def _status(config_attr: str) -> str:
        if not licensed:
            return "locked"
        if not getattr(self._config, config_attr, True):
            return "disabled"
        return "available"

    return MappingProxyType({
        "frequency": _status("frequency_enabled"),
        "escalation": _status("escalation_enabled"),
        "profiles": "available" if licensed and self._default_profile is not None
                    else ("disabled" if licensed else "locked"),
        "tool_guard": _status("tool_guard_enabled"),
        "audit": _status("audit_enabled"),
        "alerting": _status("alert_enabled"),
    })
```

Tri-state semantics:
- `"available"` — license valid + feature config enabled → feature runs
- `"disabled"` — license valid + feature config disabled → user can toggle on
- `"locked"` — no valid license → upgrade CTA

### 4. `__init__.py` exports

Add to `petasos/__init__.py`:

```python
from petasos.premium.license import LicenseClaims, LicenseState, LicenseValidator, validate_license
```

Add `"LicenseClaims"`, `"LicenseState"`, `"LicenseValidator"`, `"validate_license"` to `__all__`. This follows the existing pattern where all public premium types are re-exported at top level (`AlertManager`, `AuditEmitter`, `ToolCallGuard`, etc.).

Also add to `petasos/premium/__init__.py`: `from petasos.premium.license import LicenseClaims, LicenseState, LicenseValidator, validate_license` and extend its `__all__` accordingly.

### 5. Security hardening pass

**Immutability audit — current state and required changes:**

| Target | Current state | Action |
|--------|--------------|--------|
| `ScanResult` | `frozen=True`, `findings` is `tuple` | Already immutable. Verify only. |
| `ScanFinding` | `frozen=True` | Already immutable. Verify only. |
| `PipelineResult` | `frozen=True`, `findings` is `tuple`, `scanner_results` is `tuple`, `errors` is `tuple` | Already immutable. Verify only. |
| `AuditEvent` | `frozen=True`, `payload` is `MappingProxyType` | Already immutable. Verify only. |
| `Alert` | `frozen=True`, `context` is `MappingProxyType` | Already immutable. Verify only. |
| `LicenseClaims` | New, `frozen=True`, all fields immutable types | Correct by construction. |
| `RULE_TAXONOMY` | `frozenset[str]` in `scanners/minimal.py` | Already immutable. Verify only. |
| Built-in profiles (5 JSON configs) | `ProfileResolver.resolve()` returns cached `ResolvedProfile` directly | Already immutable. `ResolvedProfile` is frozen with all-immutable fields (`frozenset`, `MappingProxyType`, `tuple`, `float`, `str`, `None`). Verify only. |
| `PetasosConfig` | `frozen=True`, `copy()` goes through `to_dict()` → `from_dict()` (serialization round-trip) | `Pipeline.__init__` already calls `config.copy()`. The copy is deep because `to_dict()` converts tuples to lists and `MappingProxyType` to dicts, then `from_dict()` reconstructs. Verify the round-trip preserves `frequency_weights` as `MappingProxyType`. |

**Defensive copy verification points (test, don't change):**

1. `Pipeline.__init__` calls `config.copy()` — verified, line 158 of current pipeline.py.
2. `PipelineResult.findings` is `tuple[ScanFinding, ...]` — immutable by type.
3. `PipelineResult.scanner_results` is `tuple[ScanResult, ...]` — immutable by type.
4. `_build_premium_features()` returns `MappingProxyType` — verified, line 221.
5. `FrequencyTracker.get_state()` returns a defensive copy — verified, line 175-184 of frequency.py.

**No code changes needed for hardening — all exports are already frozen or wrapped.** The hardening deliverable is a test suite (`tests/test_hardening.py`) that mechanically verifies these invariants hold.

### 6. `pyproject.toml` changes

```toml
dependencies = [
    "pyjwt[crypto]>=2.8,<3",
]
```

The `[crypto]` extra pulls in `cryptography`, which provides Ed25519 support. Merge `jwt` and `jwt.*` into the existing `[[tool.mypy.overrides]]` block that already covers third-party libs (do not create a separate override block).

---

## Test plan

### `tests/test_license.py` — License validation (15+ tests)

1. Valid JWT with Ed25519 → `(VALID, LicenseClaims(...))` with correct fields
2. Expired JWT → `(EXPIRED, None)`
3. JWT with `alg: "none"` → `(INVALID, None)` — algorithm confusion prevention
4. JWT with `alg: "HS256"` using public key as secret → `(INVALID, None)`
5. JWT with `alg: "RS256"` → `(INVALID, None)`
6. Malformed token (not a JWT) → `(INVALID, None)`
7. Empty string → `(INVALID, None)`
8. JWT signed with wrong private key → `(INVALID, None)`
9. JWT missing `exp` claim → `(INVALID, None)`
10. JWT missing `iat` claim → `(INVALID, None)`
11. Clock skew within tolerance (29s past expiry) → `(VALID, ...)`
12. Clock skew beyond tolerance (31s past expiry) → `(EXPIRED, None)`
13. Token with leading/trailing whitespace → accepted, same result as stripped
14. Token with BOM prefix → accepted after stripping
15. `validate_license()` module-level function returns `LicenseState`
16. `LicenseClaims` fields are correct types (tier=str, features=frozenset, etc.)

### `tests/test_pipeline.py` updates — activate/deactivate wiring (5+ tests)

17. `pipeline.activate(valid_key)` returns `LicenseState.VALID`, premium features available
18. `pipeline.activate(invalid_key)` returns `LicenseState.INVALID`, premium stays locked
19. `pipeline.activate(expired_key)` returns `LicenseState.EXPIRED`, premium stays locked
20. `pipeline.deactivate()` clears license, session state preserved (frequency scores persist)
21. `PETASOS_LICENSE_KEY` env var auto-activates on construction when valid
22. `PETASOS_LICENSE_KEY` env var with invalid value → silent failure, OSS-only
23. Expired JWT → premium deactivates on next `inspect()` call, OSS stages still run
24. `result.premium_features` tri-state: `available`/`disabled`/`locked` for all features

### `tests/test_hardening.py` — Frozen exports + defensive copies (8+ tests)

25. `result.findings` → attempting `.append()` raises `AttributeError` (tuple)
26. `result.scanner_results` → attempting `.append()` raises `AttributeError` (tuple)
27. Mutating returned `PipelineResult` fields raises `FrozenInstanceError`
28. `RULE_TAXONOMY` → attempting `add()` raises `AttributeError` (frozenset)
29. `result.premium_features["new"]` → raises `TypeError` (MappingProxyType)
30. `AuditEvent.payload["new"]` → raises `TypeError` (MappingProxyType)
31. `Alert.context["new"]` → raises `TypeError` (MappingProxyType)
32. `PetasosConfig` copy isolation: modifying pipeline config doesn't affect original

### `tests/test_premium_integration.py` updates

33. Update all 37 `pipeline.activate()` no-arg calls to `pipeline.activate(valid_key)`
34. Update all `"unlocked"` assertions in `result.premium_features` to `"available"`
35. Update `"locked"` assertions to `"disabled"` in tests where premium is active and feature config is `False` (e.g., `test_premium_features_tool_guard_locked_when_disabled` line 337, `test_premium_features_audit_alerting_locked_when_disabled` line 459)
36. Replace `pipe._premium_active is False` / `pipe._premium_active is True` assertions in `TestActivateDeactivate` (lines 180, 182, 188) with `pipe._license_state == LicenseState.INACTIVE` / `pipe._license_state == LicenseState.VALID`

### `tests/test_guard.py` updates

37. Update 10 `pipe.activate()` no-arg calls to `pipe.activate(valid_key)`
38. Verify guard tests still pass with JWT-based activation

### `tests/test_pipeline.py` — assertion updates

39. Update 3 `p.activate()` no-arg calls to `p.activate(valid_key)` in `test_inspect_profile_override_dict`, `test_inspect_profile_override_string`, `test_is_premium_active_public`

### `tests/test_license.py` — additional edge cases

40. `LicenseValidator` with missing `public.pem` → `validate()` returns `(INVALID, None)`, no crash
41. `_check_premium()` with `license_state=VALID` but `license_claims=None` (inconsistent state) → returns `False`, self-heals to `INVALID`

### Shared test fixture

42. Create a test helper (in `tests/conftest.py` or `tests/fixtures/`) that generates valid/expired/invalid JWTs signed with the test private key (`tests/fixtures/test_private.pem`). Used across `test_license.py`, `test_pipeline.py`, `test_premium_integration.py`, and `test_guard.py`.

**Total: 42+ tests (exceeds the 25-test minimum from brief).**

---

## Test command

```
C:\python310\python.exe -m pytest tests/test_license.py tests/test_hardening.py tests/test_pipeline.py tests/test_premium_integration.py tests/test_guard.py -v
```

---

## Done when

1. `petasos/premium/license.py` exists with `LicenseValidator`, `LicenseClaims`, `LicenseState` passing `mypy --strict`.
2. `petasos/premium/_keys/public.pem` contains a test Ed25519 public key (real production key swapped at release).
3. `Pipeline.activate(key: str) -> LicenseState` validates JWT and activates premium on success.
4. `Pipeline.deactivate()` reverts to OSS-only; session state preserved.
5. Expired JWT → premium deactivates on next `inspect()` call; OSS stages still run.
6. Invalid/malformed JWT → rejected, `LicenseState.INVALID` returned, no crash.
7. Algorithm confusion attack rejected: token with `alg: "none"` or `alg: "HS256"` fails validation.
8. `PETASOS_LICENSE_KEY` env var auto-activates on pipeline construction when valid.
9. `PETASOS_LICENSE_KEY` env var with invalid value → silent failure, OSS-only.
10. `result.premium_features` manifest reports correct tri-state (`available`/`disabled`/`locked`) for all features.
11. `petasos.validate_license(key)` and `petasos.LicenseState` exported from `__init__.py`.
12. Frozen exports: mutating built-in profiles, rule taxonomy, scan results, or pipeline results raises.
13. Defensive copies: modifying a returned `PetasosConfig` or `PipelineResult` doesn't mutate pipeline internals.
14. 25+ tests (license validation + hardening + manifest).
15. `ruff check`, `ruff format`, `mypy --strict` pass.

---

## Out of scope

1. **Web service (vigilharbor.com/petasos)** — account creation, payment, key generation, dashboards. Separate project.
2. **Key rotation via `kid` header** — post-v1. v1 ships with one bundled key.
3. **CRL / phone-home revocation** — expiry-based rotation is sufficient for v1.
4. **Trial keys / time-limited premium** — noted in spec roadmap, not v1.
5. **Team/org license keys with seat management** — post-v1.
6. **In-app upgrade flow (deep link → payment → callback)** — frontend/web service concern.
7. **Audit/alerting module implementation** — that's PET-9 (shipped). PET-10 only gates them.
8. **Optional telemetry / usage analytics** — spec notes it as opt-in roadmap; not v1.

---

## Deferred (P2+)

Items identified during review that are acknowledged but not blocking:

1. **`_DEFAULT_VALIDATOR` lazy init thread-safety race** (edge-cases R1/F-1) — benign; validator is stateless and idempotent. Two threads creating separate instances wastes one allocation but is functionally correct.
2. **No input length guard on JWT token** (edge-cases R1/F-7) — PyJWT handles large inputs gracefully. A length guard (e.g., reject > 8KB) would be defense-in-depth but is low priority.
3. **Env var whitespace-only edge case** (edge-cases R1/F-9) — `" "` passes truthiness check, gets stripped to empty, rejected as INVALID. Functionally correct (silent failure). Could optimize with `if env_key and env_key.strip():` but not required.
4. **Clock skew tolerance not applied to lazy expiry check** (edge-cases R1/F-14) — minor inconsistency between PyJWT's leeway on initial validation and the hard boundary in `_check_premium()`. Token accepted within leeway could be immediately rejected by lazy check. Acceptable for v1; the 30s window is narrow.
5. **CLAUDE.md + wiki divergence on `petasos.activate(key)`** (conventions R1/F-1, F-6; edge-cases R1/F-15; conventions R2/F-1, F-6) — CLAUDE.md says `petasos.activate(key)` but `activate` is an instance method, not a module-level function. The module-level export is `validate_license(key)`. Same phrasing appears in wiki `architecture.md` (Interfaces section, line 65) and `state.md` (PET-10 entry, line 87). Update all three sources after PET-10 ships.
6. **`premium/__init__.py` re-exports** (conventions R1/F-4) — addressed in scope table (promoted from P2 to in-scope).
7. **mypy override block merging** (conventions R1/F-13) — addressed in Design §6 (promoted from P2 to in-scope).
8. **Missing custom claim validation** (edge-cases R2/F-5) — JWT with valid signature + exp/iat but missing `tier`/`customer_id` hits catch-all as `INVALID`. Functionally correct but indistinguishable from a forged key. Could add `tier`/`customer_id` to PyJWT's `require` list for clearer error messages. Low priority for v1.
9. **`_DEFAULT_VALIDATOR` singleton test isolation** (edge-cases R2/F-6) — module-level singleton retains state between tests. Tests using `validate_license()` should reset `_DEFAULT_VALIDATOR = None` in teardown or use `monkeypatch`.
10. **Non-string elements in JWT `features` claim** (edge-cases R2/F-7) — `frozenset(payload["features"])` silently accepts non-string hashable types. Could validate all elements are strings. Low priority.
11. **Hatch auto-discovery of `.pem` file** (conventions R2/F-4) — Hatch auto-discovers packages; no `pyproject.toml` include directive needed (same pattern as profiles JSON files).
