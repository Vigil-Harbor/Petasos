# Reconciliation Report: PET-10

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-10.spec.md
> Merge: PR #9 (44639fe)
> Plane state: Done (group: completed)

## Summary
PET-10 shipped JWT (Ed25519/EdDSA) license validation, tri-state premium manifest, and a frozen-export hardening test suite essentially as specified; all eight named scope files were touched and every design decision is confirmed in current code. The only gaps are test coverage: the `PETASOS_LICENSE_KEY` env-var auto-activation path (criteria 8/9) and the `_check_premium` self-heal edge (test-plan item 41) are implemented but not exercised by any test.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/premium/license.py` | Yes | New; `LicenseValidator`/`LicenseClaims`/`LicenseState`/`validate_license` all present (license.py:24-121). |
| `petasos/premium/_keys/public.pem` | Yes | New; bundled Ed25519 public key (3 lines). |
| `petasos/premium/_keys/__init__.py` | Yes | New; empty package marker for `importlib.resources`. |
| `petasos/pipeline.py` | Yes | `activate(key)`, `deactivate()`, tri-state `_check_premium`/`_build_premium_features`, env auto-activation (pipeline.py:203-313). |
| `petasos/__init__.py` | Yes | Exports + `__all__` entries for the 4 license symbols (__init__.py:20,33-35,53). |
| `petasos/premium/profiles/__init__.py` | No (expected) | Spec marked "verify only — no code changes needed"; `ResolvedProfile` frozen, so absence is correct. |
| `petasos/premium/__init__.py` | Yes | Re-exports the 4 license symbols (premium/__init__.py:13,30-32,41). |
| `pyproject.toml` | Yes | `pyjwt[crypto]>=2.8,<3` added to base deps; `jwt`/`jwt.*` merged into existing mypy overrides block (pyproject.toml:11,45-46). |
| `tests/test_license.py` | Yes | New; 20 tests. |
| `tests/test_hardening.py` | Yes | New; 14 tests. |
| `tests/test_pipeline.py` | Yes | activate/`available` migration. |
| `tests/test_premium_integration.py` | Yes | activate(valid_key) + tri-state migration (16 manifest assertions). |
| `tests/test_guard.py` | Yes | 10 `activate()` → `activate(valid_key)` migrations. |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-10.test-output.txt` — captured pytest run (167 passed); audit artifact, not source.
- `ruff.toml` — added `UP017` ignore so `timezone.utc` survives lint (lint config, not behavior; documented in commit message).
- `tests/test_presidio_scanner.py` — 3 lazy-load tests converted to async (commit notes this was a pre-existing CI failure unblocked here, unrelated to PET-10 logic).
- `tests/conftest.py` / `tests/fixtures/test_private.pem` — the shared JWT fixture helper (test-plan item 42 named conftest/fixtures as the location, so this is in-spec).

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | Ed25519, not RS256 | Confirmed | `load_pem_public_key` + `algorithms=["EdDSA"]` (license.py:67-71,87). |
| 2 | Algorithm restriction to EdDSA only | Confirmed | `algorithms=["EdDSA"]` (license.py:87); adversarial tests reject HS256 + alg:none (tests/adversarial/license/test_jwt_attacks.py:13-30). |
| 3 | Lazy expiry check, not background timer | Confirmed | Expiry checked inline in `_check_premium`, flips to EXPIRED (pipeline.py:273-276). No threads/timers. |
| 4 | No module-level singleton pipeline | Confirmed | `validate_license()` stateless module fn (license.py:116-121); `activate()` is instance method (pipeline.py:240). |
| 5 | PyJWT as base dependency | Confirmed | `dependencies = ["pyjwt[crypto]>=2.8,<3"]` (pyproject.toml:11). |
| 6 | Silent env var failure | Confirmed | `if env_key: self.activate(env_key)` with return discarded; `activate` never raises (pipeline.py:232-234,240-244). |
| 7 | Tri-state manifest replaces binary | Confirmed | `_status()` returns `locked`/`disabled`/`available` (pipeline.py:292-313). |
| 8 | Whitespace/invisible-char stripping on JWT input | Confirmed | `_INVISIBLE_RE.sub("", token.strip())` (license.py:14-16,79); tested for BOM/ZWS/whitespace (test_license.py:43-65). |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `license.py` with Validator/Claims/State, mypy --strict | Met | license.py:24-110; types annotated, `jwt` in mypy overrides (pyproject.toml:45-46). |
| 2 | `_keys/public.pem` test Ed25519 key | Met | File present (3 lines); loaded at validator init (license.py:61-71). |
| 3 | `activate(key) -> LicenseState` validates + activates | Met | pipeline.py:240-244; test_activate_enables_premium (test_premium_integration.py:183-187). |
| 4 | `deactivate()` reverts to OSS-only; session state preserved | Met | pipeline.py:246-248 clears only license; test_session_state_preserved_across_cycles (test_premium_integration.py:195). |
| 5 | Expired JWT → premium deactivates on next inspect; OSS still runs | Met | Validator returns EXPIRED (license.py:91-92; test_license.py:25-29); lazy expiry flip in `_check_premium` (pipeline.py:273-276); OSS minimal scanner always runs (pipeline.py:406). Validator-level + lazy-flip paths covered; no single test asserts the mid-session VALID→EXPIRED flip through `inspect()`, but the constituent paths are tested. |
| 6 | Invalid/malformed JWT → INVALID, no crash | Met | license.py:93-94; test_invalid_token_garbage / test_empty_string (test_license.py:31-41); test_validate_never_raises_on_garbage (adversarial/license/test_jwt_attacks.py:33-38). |
| 7 | Algorithm confusion (alg:none / HS256) rejected | Met | algorithms pin (license.py:87); test_rejects_hs256_token + test_none_alg_token_invalid (adversarial/license/test_jwt_attacks.py:13-30); test_algorithm_restriction_hs256 (test_license.py:67). |
| 8 | `PETASOS_LICENSE_KEY` auto-activates when valid (tested) | Unmet | Code present (pipeline.py:232-234) but no test sets the env var — grep for `PETASOS_LICENSE_KEY`/`setenv`/`os.environ` in tests/ returns zero hits. "(tested)" requirement not satisfied. |
| 9 | `PETASOS_LICENSE_KEY` invalid → silent failure, OSS-only (tested) | Unmet | Silent-failure code present (pipeline.py:232-234) but no env-var test exists (same grep, zero hits). |
| 10 | `premium_features` tri-state correct for all features | Met | pipeline.py:292-313; 16 manifest assertions in test_premium_integration.py; test_premium_features_is_mapping_proxy (test_hardening.py:102). |
| 11 | `validate_license` + `LicenseState` exported from `__init__` | Met | __init__.py:20,33-35,53. |
| 12 | Frozen exports raise on mutation | Met | test_scan_finding_frozen/_scan_result_frozen/_pipeline_result_frozen/_audit_event_frozen/_alert_frozen/_license_claims_frozen/_rule_taxonomy_is_frozenset/_builtin_profiles_immutable (test_hardening.py:23-122). |
| 13 | Defensive copies isolate pipeline internals | Met | `replace(config)` (pipeline.py:199); test_pipeline_config_is_copy + test_config_copy_preserves_frequency_weights (test_hardening.py:85-128). |
| 14 | ≥25 tests (license + hardening + manifest) | Met | 20 license + 14 hardening + 16 integration manifest assertions; shipped run = 167 passed (PET-10.test-output.txt). |
| 15 | ruff check, ruff format, mypy --strict pass | Met (as shipped) | Commit chain b36ca3a/ea938d3 resolved lint+typecheck; UP017 suppressed in ruff.toml. Not re-run in this read-only pass. |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| Valid JWT → (VALID, claims) | Yes | test_license.py:17 test_valid_token |
| Expired JWT → (EXPIRED, None) | Yes | test_license.py:25 test_expired_token |
| alg:"none" rejected | Yes | adversarial/license/test_jwt_attacks.py:26 test_none_alg_token_invalid |
| alg:"HS256" rejected | Yes | test_license.py:67 test_algorithm_restriction_hs256; adversarial .../test_jwt_attacks.py:13 |
| Malformed token → INVALID | Yes | test_license.py:31 test_invalid_token_garbage |
| Empty string → INVALID | Yes | test_license.py:37 test_empty_string |
| Missing exp claim → INVALID | Yes | test_license.py:122 test_missing_required_claims_exp |
| Missing iat claim → INVALID | Yes | test_license.py:133 test_missing_required_claims_iat |
| Clock skew within tolerance → VALID | Yes | test_license.py:110 test_clock_skew_tolerance |
| Clock skew beyond tolerance → EXPIRED | Yes | test_license.py:116 test_clock_skew_exceeded |
| Whitespace stripping | Yes | test_license.py:49 test_whitespace_stripping |
| BOM prefix stripping | Yes | test_license.py:55 test_bom_stripping |
| Zero-width stripping | Yes | test_license.py:61 test_zero_width_space_stripping |
| `validate_license()` module fn | Yes | test_license.py:146-153 (valid/invalid/expired) |
| LicenseClaims field types | Yes | test_license.py:79 test_claims_fields |
| Missing public.pem → INVALID, no crash | Yes | test_license.py:157 test_missing_key_returns_invalid |
| activate(valid_key) enables premium | Yes | test_premium_integration.py:183 test_activate_enables_premium |
| deactivate clears, session preserved | Yes | test_premium_integration.py:189/195 |
| Tri-state manifest available/disabled/locked | Yes | test_premium_integration.py (16 assertions); test_hardening.py:102 |
| Frozen exports (8 invariants) | Yes | test_hardening.py:23-122 |
| Config copy isolation | Yes | test_hardening.py:85,123 |
| Shared JWT fixture helper | Yes | tests/conftest.py:10-49 (valid_token/expired_token/valid_key) |
| `PETASOS_LICENSE_KEY` env auto-activation (item 21/22) | No | No env-var test in suite (grep: 0 hits). |
| `_check_premium` VALID+claims=None self-heal (item 41) | No | Self-heal code at pipeline.py:269-271; no test constructs the inconsistent state. |

## Wiki-ready
- Algorithm-confusion defense is enforced solely by PyJWT's `algorithms=["EdDSA"]` pin plus an Ed25519-only bundled key — the constraining design choice future license work must preserve (reusable across any JWT-gated feature). Adversarial coverage lives under tests/adversarial/license/ labeled "PET-14 LIC-*" though it validates the PET-10 validator.
- Tri-state premium manifest contract (`available`/`disabled`/`locked`) is a frontend-binding API surface deliberately replacing the PET-7/8/9 binary; constrains all downstream manifest consumers.

RECONCILED: no DRIFT: 3
