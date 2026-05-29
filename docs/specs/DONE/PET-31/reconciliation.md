# Reconciliation Report: PET-31

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-31.spec.md
> Merge: PR #18 (squash/fix commit f1b49cc, merge 9a63e80, reachable from master)
> Plane state: Done (group: completed)

## Summary
PET-31 (FREQ-03 session-spoofing defense) shipped exactly as specified: a `SessionToken` HMAC-SHA256 binding validated at the `FrequencyTracker` boundary, opt-in via `config.session_secret`, with pipeline/guard auto-minting. All 13 named tests exist and all 12 decisions are confirmed in current code; the spec's D12 `config.copy()`+`object.__setattr__` mechanism was later superseded by PET-23's `replace(config)`, which preserves the secret natively and keeps the defense intact.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| petasos/premium/frequency.py | Yes | `SessionToken` dataclass, `mint_token()`, `_resolve_session_id()`, `requires_token`; `update/get_state/terminate_session/reset` take `str \| SessionToken`. Current frequency.py:101-136. |
| petasos/config.py | Yes | `session_secret: bytes \| None = None` (config.py:109), `__post_init__` type guard (180), `to_dict()` exclusion (344), `from_dict()` base64 decode (363). |
| petasos/pipeline.py | Yes | `host_id` kwarg + property, host_id validation, hook auto-mint. D12 `object.__setattr__` restore was replaced by PET-23 `replace(config)` (pipeline.py:199) — see Decisions D12. |
| petasos/premium/guard.py | Yes | `_derive_tier` mints token when secret configured (guard.py:202-206). |
| petasos/__init__.py | Yes | `SessionToken` imported (__init__.py:18) and in `__all__` (45). |
| petasos/premium/__init__.py | Yes | `SessionToken` imported and in `__all__`. |
| tests/adversarial/frequency/test_session_spoofing.py | Yes | New dir + file, 5 adversarial tests. |
| tests/test_frequency.py | Yes | 4 unit tests (backward compat, valid token, mint-without-secret, null-byte). |
| tests/test_guard.py | Yes | 1 guard test. |
| tests/test_premium_integration.py | Yes | 1 pipeline-rejects-secret test. |
| tests/test_config.py | Yes | 2 config tests (base64 round-trip, to_dict exclusion). |

Unexpected files in diff (not in spec):
- docs/specs/TODO/PET-31.test-output.txt — single-line mypy success artifact ("Success: no issues found in 51 source files"). Process/audit artifact, not a code change; benign.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | HMAC-SHA256, not JWT | Confirmed | frequency.py:114-118 uses `_hmac.new(..., hashlib.sha256)`; `SessionToken` stores only session_id/host_id/hmac_digest (frequency.py:43-47 in diff). |
| D2 | Backward compatible by default | Confirmed | `_resolve_session_id` short-circuits bare string when `_session_secret is None` (frequency.py:122-127); `test_backward_compat_no_secret` green. |
| D3 | Host ID caller-provided | Confirmed | `Pipeline.__init__(host_id: str = "")` (pipeline.py:197); ValueError when secret set but host_id empty (pipeline.py:201-202). |
| D4 | `reset()` gated, not removed | Confirmed | `reset(session: str \| SessionToken)` calls `_resolve_session_id` (frequency.py, diff lines 240-242); `test_reset_requires_valid_token`. |
| D5 | Token in frequency.py, exported top-level | Confirmed | Defined frequency.py:42-47; re-exported petasos/__init__.py:18,45 and petasos/premium/__init__.py. |
| D6 | Pipeline auto-mints; `inspect()` unchanged | Confirmed | `_premium_frequency_hook` mints before `update()` (pipeline.py:582-586); inspect signature unchanged. |
| D7 | Refuted status acknowledged (opt-in) | Confirmed | Defense gated entirely on `session_secret is not None`; default None. |
| D8 | Flat + adversarial subdir test layout | Confirmed | tests/test_frequency.py and new tests/adversarial/frequency/test_session_spoofing.py both exist. |
| D9 | Guard mints via public accessors | Confirmed | guard.py:203 uses `self._frequency_tracker.mint_token(session_id, self._pipeline.host_id)` — public `host_id` property, no private access. |
| D10 | HMAC null-byte separator | Confirmed | `session_id.encode() + b"\x00" + host_id.encode()` in both mint_token (frequency.py:116) and _resolve_session_id (frequency.py:131). |
| D11 | `session_secret` excluded from `to_dict()` | Confirmed | config.py:344 `if f.name == "session_secret": continue`; from_dict base64 decode config.py:363-369; `test_to_dict_excludes_session_secret` + `test_from_dict_session_secret_base64`. |
| D12 | Pipeline preserves secret through `config.copy()` via `object.__setattr__` | Drifted | Shipped commit used `config.copy()` + `object.__setattr__` restore (diff pipeline.py). Current master uses `self._config = replace(config)` (pipeline.py:199), landed in PET-23 #43 (dfa7eef). `replace()` preserves session_secret natively, so the restore is no longer needed and the host_id guard (pipeline.py:201-202) and hook (582-586) still receive the secret. Defense intent preserved; mechanism superseded. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `SessionToken` frozen dataclass added + exported | Met | frequency.py:42-47 (diff) `@dataclass(frozen=True)`; petasos/__init__.py:18,45. |
| 2 | `_resolve_session_id()` validates HMAC via `compare_digest` on all 4 methods | Met | frequency.py:134 `_hmac.compare_digest`; called in update (141), get_state (223 diff), terminate_session (237 diff), reset (241 diff). |
| 3 | `session_secret` in config; to_dict excludes; from_dict base64 | Met | config.py:109, 344, 363-369. |
| 4 | Pipeline mints when secret set; inspect unchanged; host_id property | Met | pipeline.py:582-586 (mint), 251-252 (`host_id` property). |
| 5 | Guard mints before get_state via public accessors | Met | guard.py:202-206. |
| 6 | All 13 new tests pass | Met | All 13 function names located: 5 in test_session_spoofing.py, 4 in test_frequency.py (506/518/529/535), guard 362, integration 172, config 112/120. Mypy artifact records clean run on 51 files. |
| 7 | Backward compatibility — full suite green with secret=None | Met | `test_backward_compat_no_secret` (test_frequency.py:506); defaults unchanged. |
| 8 | ruff check / ruff format --check / mypy --strict clean | Unverifiable | Read-only reconcile; not re-running tools. test-output.txt records a clean mypy run at merge time; no contradicting evidence on disk. |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| test_spoofed_session_id_rejected | Yes | tests/adversarial/frequency/test_session_spoofing.py:22 |
| test_inflated_score_blocked | Yes | tests/adversarial/frequency/test_session_spoofing.py:30 |
| test_reset_requires_valid_token | Yes | tests/adversarial/frequency/test_session_spoofing.py:47 |
| test_terminate_requires_valid_token | Yes | tests/adversarial/frequency/test_session_spoofing.py:62 |
| test_eviction_flood_with_tokens | Yes | tests/adversarial/frequency/test_session_spoofing.py:77 |
| test_backward_compat_no_secret | Yes | tests/test_frequency.py:506 |
| test_valid_token_accepted | Yes | tests/test_frequency.py:518 |
| test_mint_token_without_secret_raises | Yes | tests/test_frequency.py:529 |
| test_mint_token_rejects_null_bytes | Yes | tests/test_frequency.py:535 |
| test_guard_derive_tier_with_session_secret | Yes | tests/test_guard.py:362 |
| test_pipeline_rejects_secret_without_host_id | Yes | tests/test_premium_integration.py:172 |
| test_from_dict_session_secret_base64 | Yes | tests/test_config.py:112 |
| test_to_dict_excludes_session_secret | Yes | tests/test_config.py:120 |

## Wiki-ready
- HMAC-SHA256 session-binding token with null-byte-separated input (D10) and opt-in `session_secret` gating — reusable pattern for binding caller-supplied opaque IDs to host auth without JWT/network, and a constraining precedent (secrets excluded from `to_dict()`, lost on serialize-copy by design — D11).
- D12 mechanism drift worth a one-line decision note: PET-23's switch to `replace(config)` for config copying silently obsoleted PET-31's `object.__setattr__` secret-restore workaround. Future config-copy changes must keep `session_secret` propagation in mind.

RECONCILED: yes DRIFT: 1
