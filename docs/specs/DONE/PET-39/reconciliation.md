# Reconciliation Report: PET-39

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-39.spec.md
> Merge: PR #37 (squash 4465985)
> Plane state: Done (group: completed)

## Summary
License hardening (LIC-04/07/08/09) shipped in PR #37 and matches the spec on all four findings and every acceptance criterion. One design-level drift: `valid_tiers` was tightened from a pure replace to a superset-of-builtins requirement during review (commits 24c3bb2/19402fb), changing the semantics of Decision/Test #13 and the empty-set error message.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/premium/license.py` | Yes | All four fixes present: fingerprint check L63-71, skew cap L47-53, tier allowlist L96-98, overflow guard L100-109. |
| `tests/test_license.py` | Yes | `test_default_tier_when_missing` renamed to `test_null_tier_rejected_by_allowlist` and flipped to expect `INVALID`/`None` (L95-100). |
| `tests/adversarial/license/test_license_hardening.py` (new) | Yes | 20 test functions covering all four findings. |
| `petasos/premium/_keys/public.pem` | No (correctly unchanged) | Spec said unchanged; LF-normalized SHA-256 = `009e2106…` matches pinned constant. |
| `petasos/premium/_keys/__init__.py` | No (correctly unchanged) | As specified. |
| `petasos/pipeline.py`, `petasos/config.py`, `tests/conftest.py`, `tests/adversarial/license/test_jwt_attacks.py` | No (correctly unchanged) | As specified. |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-39.test-output.txt` — captured pytest run as a PR audit artifact (ship-spec convention). Benign, non-code, not a behavioral change.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | Hash LF-normalized PEM bytes; fingerprint `009e2106…` | Confirmed | license.py:63-64 `raw.replace(b"\r\n", b"\n")` then `hashlib.sha256(...).hexdigest()`; recomputed live fingerprint of public.pem (116 bytes CRLF) = `009e2106b18ccb31ac1d74da4db9a9dc35097cb378e1f84688ff1b350b1bfb92` matching constant at license.py:19. |
| 2 | Tier allowlist includes `"standard"` | Confirmed | license.py:21 `frozenset({"free", "standard", "pro", "enterprise"})`. |
| 3 | Tier check on raw payload value (`str(payload.get("tier","standard"))`) | Confirmed | license.py:96-98 `tier_str = str(payload.get("tier","standard"))`; reused at L102. `tier:null` → `"None"` rejected (test_null_tier_returns_invalid L120-125). |
| 4 | Key pinning (fingerprint), not embedding | Confirmed | license.py:19 module constant + file read at L62; key not embedded as literal. |
| 5 | Clock skew cap 300 is a hard `ValueError`, not silent clamp | Confirmed | license.py:52-53 raises `ValueError` when `> 300`; L47-51 raises on non-finite/negative. |
| 6 | Fingerprint mismatch sets `_key = None` (fail-secure), no raise | Confirmed | license.py:64-65 sets `self._key = None`; `__init__` does not raise on mismatch (test_fingerprint_mismatch_nullifies_key L38-53). |
| — | (Design §1) `valid_tiers` replaces default set: `self._valid_tiers = valid_tiers if not None else _VALID_TIERS` | **Drifted** | Shipped enforces a SUPERSET: license.py:55-57 raises `ValueError("must include all built-in tiers")` if `valid_tiers` omits any builtin; L58 stores `frozenset(valid_tiers)`. Spec Test #13 expected `valid_tiers=frozenset({"custom"})` to accept `custom` and REJECT `pro`; shipped instead raises `ValueError` for that input (test_custom_tiers_missing_builtins_rejected L178-180). Stricter and more secure than spec, but a behavioral change from the documented design and from spec Tests #13/#14. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Replacing `public.pem` → all `validate()` return `INVALID` | Met | license.py:64-65 + 76-77; test_swapped_key_returns_invalid (hardening L20-35). |
| 2 | Fingerprint platform-independent (LF-normalized) | Met | license.py:63 `raw.replace(b"\r\n", b"\n")`; Decision 1 above. |
| 3 | `exp=10**18` → `INVALID`, no exception | Met | license.py:104+108 try/except `OverflowError`; test_exp_overflow_returns_invalid (L66-71). |
| 4 | `exp=float("inf")` → `INVALID`, no exception | Met | same guard; test_exp_infinity_returns_invalid (L74-79). |
| 5 | Malformed `features` (int) → `INVALID`, no exception | Met | `TypeError` in except at license.py:108; test_malformed_features_returns_invalid (L99-104). |
| 6 | `tier="superadmin"` → `INVALID` | Met | license.py:97-98; test_unknown_tier_returns_invalid (L112-117). |
| 7 | `tier=None` (JSON null) → `INVALID` | Met | `str(None)="None"` not in set; test_null_tier_returns_invalid (L120-125). |
| 8 | `tier=""` → `INVALID` | Met | empty string not in set; test_empty_tier_returns_invalid (L128-133). |
| 9 | Missing `tier` → `VALID`, `claims.tier == "standard"` | Met | license.py:96 default `"standard"`; test_missing_tier_defaults_to_standard (L146-160). |
| 10 | `clock_skew_seconds=1e9` raises `ValueError` | Met | license.py:52-53; test_clock_skew_extreme (L213-215). |
| 11 | `clock_skew_seconds=300` accepted (boundary) | Met | license.py:52 uses `> 300`; test_clock_skew_cap_boundary (L198-200). |
| 12 | `clock_skew_seconds=-1` raises `ValueError` | Met | license.py:47-51; test_clock_skew_negative (L203-205). |
| 13 | `clock_skew_seconds=float("nan")` raises `ValueError` | Met | `math.isfinite` guard L47; test_clock_skew_nan (L208-210). |
| 14 | `LicenseValidator(valid_tiers=frozenset())` raises `ValueError` | Met (message changed) | license.py:55-57 raises (empty set fails subset check); test_empty_valid_tiers_rejected (L183-185). Message is "must include all built-in tiers" not spec's "must not be empty" — drift folded into Decision-§1 drift. |
| 15 | `valid_tiers` parameter overrides default tier set | Met (semantics narrowed) | license.py:55-58; test_custom_valid_tiers (L163-176) — override works but only as a SUPERSET; cannot narrow below builtins. |
| 16 | ≥19 tests in hardening file | Met | 20 test functions (grep count). |
| 17 | `test_default_tier_when_missing` updated to expect `INVALID` | Met | Renamed to `test_null_tier_rejected_by_allowlist`, asserts `INVALID`/`None` (test_license.py:95-100). |
| 18 | `mypy --strict` clean | Unverifiable | Not re-run here (read-only); PET-39.test-output.txt artifact in diff is the recorded CI evidence. |
| 19 | Existing license tests still pass (except updated) | Unverifiable | Not re-run; code paths intact, no removed assertions. |
| 20 | `ruff check .` / `ruff format --check .` clean | Unverifiable | Not re-run here. |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| test_swapped_key_returns_invalid | Yes | tests/adversarial/license/test_license_hardening.py:20 |
| test_fingerprint_mismatch_nullifies_key | Yes | test_license_hardening.py:38 |
| test_correct_fingerprint_loads_key | Yes | test_license_hardening.py:56 |
| test_exp_overflow_returns_invalid | Yes | test_license_hardening.py:66 |
| test_exp_infinity_returns_invalid | Yes | test_license_hardening.py:74 |
| test_iat_overflow_returns_invalid | Yes | test_license_hardening.py:82 |
| test_malformed_features_returns_invalid | Yes | test_license_hardening.py:99 |
| test_unknown_tier_returns_invalid | Yes | test_license_hardening.py:112 |
| test_null_tier_returns_invalid | Yes | test_license_hardening.py:120 |
| test_empty_tier_returns_invalid | Yes | test_license_hardening.py:128 |
| test_valid_tiers_accepted (param x4) | Yes | test_license_hardening.py:136 |
| test_missing_tier_defaults_to_standard | Yes | test_license_hardening.py:146 |
| test_custom_valid_tiers | Yes (semantics changed) | test_license_hardening.py:163 |
| test_custom_tiers_missing_builtins_rejected (new, not in spec) | Yes | test_license_hardening.py:178 |
| test_empty_valid_tiers_rejected | Yes (message changed) | test_license_hardening.py:183 |
| test_clock_skew_cap_exceeded | Yes | test_license_hardening.py:193 |
| test_clock_skew_cap_boundary | Yes | test_license_hardening.py:198 |
| test_clock_skew_negative | Yes | test_license_hardening.py:203 |
| test_clock_skew_nan | Yes | test_license_hardening.py:208 |
| test_clock_skew_extreme | Yes | test_license_hardening.py:213 |
| test_null_tier_rejected_by_allowlist (renamed from test_default_tier_when_missing) | Yes | tests/test_license.py:95 |

## Wiki-ready
- `valid_tiers` is a superset-only override, not a replace. Callers may ADD custom tiers but cannot narrow the allowlist below the built-in `{free, standard, pro, enterprise}` — passing a set missing any builtin (including the empty set) raises `ValueError`. This diverges from the spec's documented replace-semantics and is a deliberate review-time hardening (prevents a misconfigured caller from rejecting legitimate enterprise/pro tokens). Constraining for any future custom-tier integration.

RECONCILED: yes DRIFT: 2
