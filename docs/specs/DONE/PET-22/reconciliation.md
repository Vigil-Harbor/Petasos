# Reconciliation Report: PET-22

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-22.spec.md
> Merge: PR #14 (d8cacae; content 61cab8d)
> Plane state: Done (group: completed)

## Summary
PET-22 (AUD-03: redact secrets from verbose audit payloads) shipped exactly as specified — `_SECRET_FIELDS` registry, opt-in `to_dict(redact_secrets=...)`, and the single audit call-site change are all present on disk with all 6 tests. No drift attributable to this spec.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/config.py` | Yes | `_SECRET_FIELDS` frozenset added (now L40); `redact_secrets` kwarg added to `to_dict` (now L341). |
| `petasos/premium/audit.py` | Yes | `config_snapshot` now uses `to_dict(redact_secrets=True)` (now L105). |
| `tests/test_config.py` | Yes | `TestSecretRedaction` class with 4 tests added (L194). |
| `tests/test_audit.py` | Yes | 2 verbose-payload redaction tests added (L294, L306). |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-22.test-output.txt` — ship-spec test-audit artifact, not a code change; standard for this repo's lifecycle, not drift.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | Opt-in redaction, not always-on (`redact_secrets=False` default) | Confirmed | `petasos/config.py:341` `def to_dict(self, *, redact_secrets: bool = False)`; default path preserved by `test_to_dict_default_preserves_hash_key` (tests/test_config.py:206). |
| 2 | Sentinel `"[REDACTED]"`, not omission; `None` stays `None`; key always present | Confirmed | `petasos/config.py:347-349` `d[f.name] = "[REDACTED]" if val is not None else None; continue`. |
| 3 | `_SECRET_FIELDS` as module-level `frozenset[str]` (the single registry) | Confirmed | `petasos/config.py:40` `_SECRET_FIELDS: frozenset[str] = frozenset({"hash_key"})`; imported directly in tests/test_config.py:7. |
| 4 | No impact on `copy()` — secrets round-trip via default `to_dict()` | Confirmed | `copy()` calls `from_dict(to_dict())` with no flag; default path unredacted (config.py:341); regression guarded by `test_to_dict_default_preserves_hash_key`. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `_SECRET_FIELDS` frozenset defined in `petasos/config.py` | Met | `petasos/config.py:40`. |
| 2 | `to_dict(redact_secrets=True)` replaces secret values with `"[REDACTED]"` | Met | `petasos/config.py:347-349`. |
| 3 | `_build_payload` calls `to_dict(redact_secrets=True)` for `config_snapshot` | Met | `petasos/premium/audit.py:105`. |
| 4 | All 6 new tests pass | Met | All 6 present on disk (tests/test_config.py:195-211, tests/test_audit.py:294/306); PET-22.test-output.txt records 46 passed incl. all 6. |
| 5 | `ruff check .` and `mypy --strict .` clean | Unverifiable | Not re-run (read-only reconcile). Artifact records "ruff: All checks passed", "mypy --strict petasos/: Success". |
| 6 | No regression in `pytest` full suite | Unverifiable | Not re-run. Artifact records "542 passed, 28 skipped, 2 errors (pre-existing benchmark errors)". |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| `test_to_dict_redact_secrets_masks_hash_key` | Yes | tests/test_config.py:195 |
| `test_to_dict_redact_secrets_none_stays_none` | Yes | tests/test_config.py:200 |
| `test_to_dict_default_preserves_hash_key` | Yes | tests/test_config.py:206 |
| `test_secret_fields_subset_of_config_fields` | Yes | tests/test_config.py:211 |
| `test_verbose_payload_redacts_hash_key` | Yes | tests/test_audit.py:294 |
| `test_verbose_payload_no_raw_secret_in_str` | Yes | tests/test_audit.py:306 |

## Wiki-ready
- Centralized secret registry pattern: `_SECRET_FIELDS` frozenset + opt-in `to_dict(redact_secrets=True)` keeps `copy()` round-trip intact while the audit path is the sole redacting consumer. The `test_secret_fields_subset_of_config_fields` guard catches typos but NOT omissions — adding a new secret config field without registering it silently leaks (deferred P2, mitigated only by review checklist). This is the constraining/reusable takeaway for future secret-bearing config fields (e.g., `session_secret`, later added by PET-31, is independently skipped in `to_dict` rather than routed through `_SECRET_FIELDS`).

RECONCILED: yes DRIFT: 0
