# PET-31 — FREQ-03: Session-ID Spoofing / Score Inflation

**Plane:** PET-31 · **Finding:** FREQ-03 · **Priority:** Urgent  
**OWASP:** ASI07 — Unauthenticated session manipulation  
**Parent:** PET-14 · **Blocks:** PET-12 (release)  
**Status:** Refuted → ready-for-dev

---

## Problem

`FrequencyTracker.update()` at L87 of `petasos/premium/frequency.py` accepts a bare `session_id: str` with no authentication or binding to the calling host. The tracker stores per-session state in `self._sessions` (L84), keyed solely by this string. Any caller that knows (or guesses) a victim's session ID can:

1. **Inflate the victim's score** — call `update("victim-session", [high_weight_rules])` repeatedly. The victim's `SessionState.last_score` (L27) climbs until `evaluate_tier` at L157 returns `"tier3"`, setting `state.terminated = True` at L164–165. The legitimate user is now permanently blocked.

2. **Trigger eviction of other sessions** — by flooding `update()` with new spoofed session IDs, an attacker can push `len(self._sessions)` past `self._max_sessions` (L54), triggering `_evict_one` at L122–123. The eviction logic at L211–228 preferentially evicts terminated sessions first (L218–221, L225–226), meaning a previously-terminated attacker session could be silently freed — chaining into FREQ-02.

3. **Launder own score** — call `reset("attacker-session")` at L191–192 to delete own state entirely, then re-create with a clean `SessionState` on next `update()`.

The root cause: `session_id` is a caller-supplied opaque string with no cryptographic binding to the originating host, process, or auth context.

## Prior Art

Drawbridge's TypeScript `FrequencyTracker` (`clawmoat-drawbridge-sanitizer/src/frequency/index.ts`) has the identical vulnerability — `update(sessionId, ruleIds)` at L126 accepts a bare string with no auth binding. This is net-new defense for Petasos.

Session fixation / session spoofing is a well-documented attack class (OWASP Session Management). In the AI agent context, ASI07 covers manipulation of session-level state to evade or weaponize safety controls.

## Remediation

### Approach: Bind session_id to host auth via HMAC token

Introduce a `SessionToken` that cryptographically binds a session ID to the host that created it. The tracker validates the token before accepting any state mutation.

### Changes

**1. `petasos/premium/frequency.py` — session token validation**

Add a `SessionToken` dataclass and validation to `update()`, `terminate_session()`, `reset()`, and `get_state()`:

```python
@dataclass(frozen=True)
class SessionToken:
    session_id: str
    host_id: str
    hmac_digest: str  # HMAC-SHA256(session_id + host_id, secret)
```

In `__init__()`, accept an optional `session_secret: bytes` parameter. When provided, all public methods require a `SessionToken` instead of a bare `session_id`. The HMAC is verified before any state lookup:

```python
def _verify_token(self, token: SessionToken) -> bool:
    if self._session_secret is None:
        return True  # backward compat: no secret = no binding
    expected = hmac.new(
        self._session_secret,
        f"{token.session_id}:{token.host_id}".encode(),
        "sha256",
    ).hexdigest()
    return hmac.compare_digest(expected, token.hmac_digest)
```

Guard every public method entry point:

- `update()` (L87): verify token before Step 1
- `get_state()` (L175): verify token before lookup
- `terminate_session()` (L186): verify token before mutation
- `reset()` (L191): verify token before deletion

**2. `petasos/config.py` — config surface**

Add `session_secret: bytes | None = None` to `PetasosConfig`. When `None`, token validation is skipped (backward compatible for OSS tier). When set, all frequency operations require valid tokens.

**3. `petasos/pipeline.py` — token minting**

The pipeline mints `SessionToken` instances at session creation time, binding the session ID to the host context provided by the consumer (Hermes agent). The token is passed through to all frequency tracker calls.

**4. Caller contract (Hermes integration)**

Hermes must provide a stable `host_id` (e.g., machine fingerprint or process UUID) at pipeline init. The `session_secret` should be derived from the premium license key or a dedicated secret, never hardcoded.

### Backward Compatibility

When `session_secret` is `None` (default), all methods accept bare `session_id` strings exactly as today. Token validation only activates when a secret is configured. This preserves OSS-tier behavior and existing tests.

## Tests Required

| Test | File | Asserts |
|------|------|---------|
| `test_spoofed_session_id_rejected` | `tests/adversarial/frequency/test_session_spoofing.py` | `update()` with invalid HMAC returns error / raises when secret is configured |
| `test_inflated_score_blocked` | `tests/adversarial/frequency/test_session_spoofing.py` | Attacker cannot inflate victim score when tokens are enforced |
| `test_reset_requires_valid_token` | `tests/adversarial/frequency/test_session_spoofing.py` | `reset()` with wrong host_id HMAC is rejected |
| `test_terminate_requires_valid_token` | `tests/adversarial/frequency/test_session_spoofing.py` | `terminate_session()` with spoofed token is rejected |
| `test_backward_compat_no_secret` | `tests/unit/premium/test_frequency.py` | When `session_secret=None`, bare `session_id` strings still work as before |
| `test_valid_token_accepted` | `tests/unit/premium/test_frequency.py` | Correctly minted token passes validation and updates state normally |
| `test_eviction_flood_with_tokens` | `tests/adversarial/frequency/test_session_spoofing.py` | Attacker cannot flood sessions with spoofed IDs to trigger eviction of legitimate sessions |

## Decisions Carried Forward

- **Backward compatible by default.** Token validation is opt-in via `session_secret`. OSS tier and existing tests are unaffected. Premium consumers are expected to configure the secret.
- **HMAC-SHA256, not signed JWT.** The token is a simple HMAC binding, not a full JWT. JWTs are overkill for an in-process binding — there's no network, no expiry, no audience claim needed. The license JWT already handles premium gating.
- **Host ID is caller-provided.** Petasos does not fingerprint the host itself — that's the consumer's responsibility. This keeps Petasos portable across macOS and Windows (Hermes Desktop's two platforms).
- **`reset()` gated, not removed.** Legitimate callers need `reset()` for session cleanup. Gating it behind token validation prevents attacker abuse without removing functionality.
- **Refuted status acknowledged.** This finding was refuted during triage (session_id spoofing requires the attacker to be in-process, which implies full compromise). The brief documents the defense regardless — defense-in-depth against partial-compromise scenarios where an attacker controls one session but not the host secret.

## Done When

- [ ] `SessionToken` dataclass added to `petasos/premium/frequency.py`
- [ ] `_verify_token()` added and called at entry of `update()`, `get_state()`, `terminate_session()`, `reset()`
- [ ] `session_secret` added to `PetasosConfig` with `None` default
- [ ] Pipeline mints tokens when secret is configured
- [ ] All 7 tests listed above pass
- [ ] Backward compatibility confirmed: full test suite passes with `session_secret=None`
- [ ] `ruff check .` and `mypy --strict .` clean

## Out of Scope

- Session ID format validation (e.g., UUID enforcement) — separate concern
- Network-level session binding (TLS channel binding) — Petasos is in-process, no network
- Rate limiting on token validation failures — could be added but is separate from the core fix
- Drawbridge backport — uncoupled project, own ticket if needed
- Token expiry / rotation — unnecessary for in-process HMAC; the session TTL (`session_ttl_seconds`) already handles staleness
