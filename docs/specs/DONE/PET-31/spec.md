# PET-31 — FREQ-03: Session-ID Spoofing / Score Inflation

**Ticket:** PET-31 ("[RT FREQ-03] Spoof victim session_id + injection hits") · Plane `fdbb65a4-bef6-4d15-96fa-357ebf2cd279` · Urgent
**Finding:** FREQ-03 (`external_id`) · **Parent:** PET-14 · **Blocks:** PET-12 (release) · **OWASP:** ASI07 (unauthenticated session manipulation)
**Brief:** `docs/specs/TODO/PET-31.brief.md` · **Grounded against:** repo HEAD `d0af5aa` (`frequency.py`/`pipeline.py`/`config.py` unchanged since they last landed)

---

## Goal

Close the FREQ-03 session-spoofing vulnerability: any caller that knows a victim's `session_id` can inflate their frequency score, trigger tier-3 termination, flood the session table to trigger eviction, or launder their own score via `reset()`. The fix introduces a `SessionToken` — an HMAC-SHA256 binding of `session_id + host_id` to a shared secret — validated at the frequency tracker boundary. When `session_secret` is configured, all tracker mutations require a valid token; without it, bare `session_id` strings still work (backward compatible for OSS tier and existing tests).

---

## Scope

### Files to change (source)
- `petasos/premium/frequency.py` — add `SessionToken` dataclass, `_resolve_session_id` helper, `mint_token()` public method, `requires_token` property; update `update()`, `get_state()`, `terminate_session()`, `reset()` signatures to accept `str | SessionToken`.
- `petasos/config.py` — add `session_secret: bytes | None = None` to `PetasosConfig`; update `to_dict()` to exclude `session_secret`; update `from_dict()` to accept base64-encoded secret; add `__post_init__` type guard.
- `petasos/pipeline.py` — store `host_id` from constructor kwarg; add `host_id` read-only property; auto-mint `SessionToken` before calling frequency tracker when secret is configured.
- `petasos/premium/guard.py` — mint token before calling `self._frequency_tracker.get_state()` in `_derive_tier`.
- `petasos/__init__.py` — add `SessionToken` to imports and `__all__`.

### Files to change (tests)
- `tests/adversarial/frequency/test_session_spoofing.py` **(new directory + file)** — 5 adversarial tests per brief.
- `tests/test_frequency.py` — add 3 unit tests: backward compat, valid token acceptance, mint-without-secret error.
- `tests/test_guard.py` — add 1 test: guard `_derive_tier` with `session_secret` configured.
- `tests/test_premium_integration.py` — add 1 test: Pipeline constructor rejects `session_secret` without `host_id`.
- `tests/test_config.py` — add 2 tests: `from_dict` base64 round-trip, `to_dict` exclusion.

### Files to leave alone
- `petasos/premium/escalation.py` — `evaluate_tier` takes a score float, not a session_id; unaffected.
- `petasos/premium/audit.py` / `petasos/premium/alerting.py` — these receive `session_id: str | None` for logging/tracking purposes; they do not mutate frequency state; no token needed.
- `petasos/premium/profiles/` — entirely unrelated.
- Built-in profile JSONs — unchanged.

---

## Decisions

### D1 — HMAC-SHA256, not signed JWT (carried from brief)
The token is a simple HMAC binding (`hmac.new(secret, session_id\0host_id, sha256)`), not a JWT. **Why:** JWTs are overkill for an in-process binding — no network, no expiry, no audience claim. The license JWT already handles premium gating. HMAC-SHA256 is fast, stdlib-only (`hmac` + `hashlib`), and provides the exact binding needed. **How honored:** `SessionToken` stores only `session_id`, `host_id`, and `hmac_digest`; no JWT parsing.

### D2 — Backward compatible by default (carried from brief)
When `session_secret` is `None` (default), all public methods accept bare `session_id: str` exactly as today. Token validation only activates when a secret is configured. **Why:** OSS tier has no premium features; existing tests pass `session_id` as a string everywhere. Breaking that API for a defense against in-process spoofing (itself refuted as low-risk) is not worth the churn. **How honored:** every public method's union type `str | SessionToken` is resolved in `_resolve_session_id`, which short-circuits to the bare string when no secret is configured.

### D3 — Host ID is caller-provided (carried from brief)
Petasos does not fingerprint the host. `host_id` is a string provided by the consumer (Hermes) at `Pipeline` construction time. **Why:** keeps Petasos portable across macOS/Windows without platform-specific fingerprinting code. The consumer already knows its identity (machine fingerprint, process UUID, etc.). **How honored:** `Pipeline.__init__` accepts `host_id: str = ""`. When `session_secret` is configured but `host_id` is empty, a `ValueError` is raised (misconfiguration signal).

### D4 — `reset()` gated, not removed (carried from brief)
Legitimate callers need `reset()` for session cleanup. Gating it behind token validation prevents attacker abuse without removing functionality. **How honored:** `reset()` accepts `str | SessionToken`; when secret is configured, a bare string or invalid HMAC raises `ValueError`.

### D5 — Token lives in `frequency.py`, exported from top-level `petasos`
`SessionToken` is a 3-field frozen dataclass used primarily by `FrequencyTracker`. It is defined in `frequency.py` and re-exported from `petasos/__init__.py` (alongside `FrequencyTracker`, `FrequencyUpdateResult`), consistent with how every other public frozen dataclass is exported. **How honored:** `petasos/__init__.py` gets updated imports and `__all__`.

### D6 — Pipeline auto-mints tokens internally; public `inspect()` API unchanged
`Pipeline.inspect()` keeps its signature `session_id: str | None`. When `session_secret` is configured, the pipeline internally calls `self._frequency_tracker.mint_token(session_id, self._host_id)` and passes the resulting `SessionToken` to the frequency hook. Consumers don't need to mint tokens themselves for the normal pipeline path. **Why:** the defense targets direct `FrequencyTracker` access (the bypass path), not the pipeline path (which is already trusted). Changing `inspect()`'s signature would break every existing consumer for a defense they don't invoke directly. **How honored:** `_premium_frequency_hook` mints before calling `update()`.

### D7 — Refuted status acknowledged (carried from brief)
This finding was refuted during triage (session_id spoofing requires in-process access, implying full compromise). The spec implements the defense regardless — defense-in-depth against partial-compromise scenarios where an attacker controls one session but not the host secret (e.g., a jailbroken LLM agent in a sandboxed execution context). **How honored:** the defense is implemented but is opt-in, not forced.

### D8 — Tests land in flat layout + adversarial subdirectory (drift correction)
The brief specifies `tests/unit/premium/test_frequency.py`. That directory does not exist; the repo uses `tests/test_frequency.py` for unit tests. Adversarial tests go under `tests/adversarial/frequency/` (new subdirectory, consistent with existing `guard/`, `normalization/`, etc.). **How honored:** test plan below uses real paths.

### D9 — Guard mints token via tracker; uses public accessors only
`ToolCallGuard._derive_tier()` calls `self._frequency_tracker.get_state(session_id)`. When secret is configured, the guard must provide a token. The guard checks `self._config.session_secret is not None` (the config is already available via `self._config`), then calls `self._frequency_tracker.mint_token(session_id, self._pipeline.host_id)` using Pipeline's public `host_id` property. No private-attribute cross-boundary access. **How honored:** guard uses `self._config.session_secret`, `self._pipeline.host_id`, and the tracker's public `mint_token` method.

### D10 — HMAC message uses null-byte separator (security hardening)
The HMAC input is `session_id.encode() + b'\x00' + host_id.encode()` rather than a colon-delimited string. **Why:** colon delimiting creates ambiguity (`session_id="a:b" + host_id="c"` == `session_id="a" + host_id="b:c"`). Null-byte separator is unambiguous because session IDs and host IDs should not contain null bytes. **How honored:** both `mint_token()` and `_resolve_session_id()` use the null-byte format.

### D11 — `session_secret` excluded from `to_dict()` serialization
`to_dict()` omits `session_secret` from its output. **Why:** secrets must not appear in JSON-serialized config (audit trails, debug logging, frontend binding). `from_dict()` accepts an optional `session_secret` as base64-encoded string and decodes it. `copy()` chains through `to_dict()` → `from_dict()` — the secret is lost on copy, which is the safe default for external callers. **How honored:** `to_dict()` skips the field; `from_dict()` handles base64 decoding.

### D12 — Pipeline preserves `session_secret` through its internal `config.copy()` call
`Pipeline.__init__` at `pipeline.py:161` calls `config.copy()` to get a defensive copy. Since D11 excludes `session_secret` from `to_dict()`, the copy loses the secret — which would silently disable the entire token defense. **Fix:** after calling `config.copy()`, Pipeline restores `session_secret` from the original config using `object.__setattr__` (the same pattern already used in `PetasosConfig.__post_init__` for `pii_entities` at `config.py:85`). This ensures `self._config.session_secret` retains the caller's value, the `FrequencyTracker(self._config)` at `pipeline.py:182` receives the secret, and all downstream checks on `self._config.session_secret` work correctly. The `to_dict()` exclusion still protects against accidental serialization. **How honored:** Change 4 explicitly addresses the `config.copy()` interaction.

### D13 — `mint_token()` rejects null bytes in session_id and host_id
`session_id` and `host_id` must not contain embedded `\x00` characters. **Why:** the HMAC input uses a null-byte separator (D10). An embedded null byte in either field would create ambiguity: `session_id="a\x00b"` + `host_id="c"` produces the same HMAC input as `session_id="a"` + `host_id="b\x00c"`. **How honored:** `mint_token()` validates both fields and raises `ValueError` on embedded null bytes.

---

## Design

### Change 1 — `SessionToken` and `mint_token()` (`frequency.py`)

Add at module top, after existing imports:

```python
import hashlib
import hmac

@dataclass(frozen=True)
class SessionToken:
    session_id: str
    host_id: str
    hmac_digest: str
```

Add public property on `FrequencyTracker`:

```python
@property
def requires_token(self) -> bool:
    return self._session_secret is not None
```

Add public method on `FrequencyTracker`:

```python
def mint_token(self, session_id: str, host_id: str) -> SessionToken:
    if self._session_secret is None:
        raise ValueError("cannot mint token: no session_secret configured")
    if not session_id:
        raise ValueError("session_id must be non-empty")
    if not host_id:
        raise ValueError("host_id must be non-empty")
    if "\x00" in session_id or "\x00" in host_id:
        raise ValueError("session_id and host_id must not contain null bytes")
    digest = hmac.new(
        self._session_secret,
        session_id.encode() + b"\x00" + host_id.encode(),
        hashlib.sha256,
    ).hexdigest()
    return SessionToken(session_id=session_id, host_id=host_id, hmac_digest=digest)
```

Add private helper:

```python
def _resolve_session_id(self, session: str | SessionToken) -> str:
    if isinstance(session, str):
        if self._session_secret is not None:
            raise ValueError(
                "session_secret is configured: pass a SessionToken, not a bare string"
            )
        return session
    if self._session_secret is not None:
        expected = hmac.new(
            self._session_secret,
            session.session_id.encode() + b"\x00" + session.host_id.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, session.hmac_digest):
            raise ValueError("invalid session token: HMAC verification failed")
    return session.session_id
```

Update `__init__` to store secret:

```python
def __init__(self, config: PetasosConfig) -> None:
    ...
    self._session_secret: bytes | None = config.session_secret
```

### Change 2 — Update public methods (`frequency.py`)

Each public method's `session_id: str` parameter becomes `session: str | SessionToken`. The first line calls `session_id = self._resolve_session_id(session)`, then proceeds as before.

Methods to update: `update()`, `get_state()`, `terminate_session()`, `reset()`.

`clear()` and the `size` property have no session parameter and are unaffected.

### Change 3 — `PetasosConfig` (`config.py`)

Add field after `max_new_sessions_per_minute`:

```python
session_secret: bytes | None = None
```

Add `__post_init__` validation:

```python
if self.session_secret is not None and not isinstance(self.session_secret, bytes):
    raise ValueError(
        f"session_secret must be bytes or None, got {type(self.session_secret).__name__}"
    )
```

Update `to_dict()` — exclude `session_secret`:

```python
def to_dict(self) -> dict[str, Any]:
    d: dict[str, Any] = {}
    for f in fields(self):
        if f.name == "session_secret":
            continue  # secrets must not appear in serialized config
        ...
```

Update `from_dict()` — accept optional base64-encoded secret:

```python
@classmethod
def from_dict(cls, data: dict[str, Any]) -> PetasosConfig:
    known = {f.name for f in fields(cls)}
    filtered = {k: v for k, v in data.items() if k in known}
    if "pii_entities" in filtered and isinstance(filtered["pii_entities"], list):
        filtered["pii_entities"] = tuple(filtered["pii_entities"])
    if "session_secret" in filtered and isinstance(filtered["session_secret"], str):
        import base64
        try:
            filtered["session_secret"] = base64.b64decode(filtered["session_secret"])
        except Exception:
            raise ValueError("session_secret must be valid base64") from None
    return cls(**filtered)
```

**Note on `copy()`:** `copy()` chains `from_dict(to_dict())`. Since `to_dict()` excludes `session_secret`, the copy has `session_secret=None`. This is the safe default — secrets are not implicitly propagated through serialization. Callers who need to preserve the secret must pass it explicitly.

### Change 4 — Pipeline token minting (`pipeline.py`)

Add `host_id` parameter to `Pipeline.__init__` (preserving the existing signature):

```python
def __init__(
    self,
    scanners: Sequence[Scanner] = (),
    *,
    config: PetasosConfig | None = None,
    profile: str | ResolvedProfile | None = None,
    on_audit: Callable[[AuditEvent], None] | None = None,
    on_alert: Callable[[Alert], None] | None = None,
    host_id: str = "",
) -> None:
    ...  # existing: self._config = config.copy() if config is not None else PetasosConfig()
    # D12: restore session_secret after copy (copy() strips it per D11)
    if config is not None and config.session_secret is not None:
        object.__setattr__(self._config, "session_secret", config.session_secret)
    self._host_id = host_id
    if self._config.session_secret is not None and not host_id:
        raise ValueError("host_id is required when session_secret is configured")
```

**Critical note (D12):** the `object.__setattr__` call must come BEFORE `self._host_id` assignment and the validation guard. It must also come BEFORE `FrequencyTracker(self._config)` at `pipeline.py:182`, so the tracker receives the secret. The existing constructor body already creates the tracker after config initialization, so inserting the restore immediately after the `config.copy()` line satisfies this ordering.

Add public read-only property:

```python
@property
def host_id(self) -> str:
    return self._host_id
```

Update `_premium_frequency_hook` to mint token when secret is configured:

```python
async def _premium_frequency_hook(
    self, findings: tuple[ScanFinding, ...], session_id: str | None
) -> FrequencyUpdateResult | None:
    ...  # existing premium checks
    if session_id is None:
        return None
    rule_ids = [f.rule_id for f in findings]
    if self._config.session_secret is not None:
        token = self._frequency_tracker.mint_token(session_id, self._host_id)
        return self._frequency_tracker.update(token, rule_ids)
    return self._frequency_tracker.update(session_id, rule_ids)
```

**Degradation note:** if `mint_token()` raises `ValueError` (e.g., inconsistent state), the existing `try/except Exception` in `_inspect_inner` catches it and appends the error string to `result.errors`. The pipeline continues with `freq_result = None` — frequency tracking is silently skipped for that call. This is consistent with the "Pipeline never throws" invariant.

### Change 5 — Guard token minting (`guard.py`)

Update `_derive_tier` to pass a token when secret is configured, using public accessors only:

```python
def _derive_tier(self, session_id: str) -> str:
    if self._config.session_secret is not None:
        token = self._frequency_tracker.mint_token(session_id, self._pipeline.host_id)
        state = self._frequency_tracker.get_state(token)
    else:
        state = self._frequency_tracker.get_state(session_id)
    ...
```

### Change 6 — Exports (`petasos/__init__.py` and `petasos/premium/__init__.py`)

Add `SessionToken` to the import line from `petasos.premium.frequency` and to `__all__` in both `petasos/__init__.py` and `petasos/premium/__init__.py`, consistent with the existing re-export chain for `FrequencyUpdateResult`.

---

## Test plan

All tests use the repo's existing layout (D8). New tests:

| Test | File | Asserts |
|------|------|---------|
| `test_spoofed_session_id_rejected` | `tests/adversarial/frequency/test_session_spoofing.py` | `update()` with invalid HMAC raises `ValueError` when secret is configured |
| `test_inflated_score_blocked` | `tests/adversarial/frequency/test_session_spoofing.py` | Attacker cannot inflate victim score: `update()` with forged token for victim session raises `ValueError` |
| `test_reset_requires_valid_token` | `tests/adversarial/frequency/test_session_spoofing.py` | `reset()` with wrong `host_id` HMAC is rejected |
| `test_terminate_requires_valid_token` | `tests/adversarial/frequency/test_session_spoofing.py` | `terminate_session()` with spoofed token is rejected |
| `test_backward_compat_no_secret` | `tests/test_frequency.py` | When `session_secret=None` (default), bare `session_id` strings work exactly as before — `update()`, `get_state()`, `reset()`, `terminate_session()` all accept strings |
| `test_valid_token_accepted` | `tests/test_frequency.py` | Correctly minted token passes validation: `mint_token()` → `update()` → `get_state()` returns valid `SessionState` |
| `test_mint_token_without_secret_raises` | `tests/test_frequency.py` | `mint_token()` raises `ValueError` when `session_secret` is `None` |
| `test_eviction_flood_with_tokens` | `tests/adversarial/frequency/test_session_spoofing.py` | Attacker cannot flood sessions with spoofed IDs: `update()` with forged tokens for many session IDs all raise `ValueError` — legitimate sessions are not evicted |
| `test_guard_derive_tier_with_session_secret` | `tests/test_guard.py` | Construct Pipeline with `host_id` and `session_secret`; insert session state; verify `_derive_tier` mints token and `get_state` succeeds |
| `test_pipeline_rejects_secret_without_host_id` | `tests/test_premium_integration.py` | `Pipeline(config=PetasosConfig(session_secret=b"key"), host_id="")` raises `ValueError` |
| `test_from_dict_session_secret_base64` | `tests/test_config.py` | `PetasosConfig.from_dict({"session_secret": base64.b64encode(b"my-secret").decode()})` produces config with `session_secret == b"my-secret"` |
| `test_to_dict_excludes_session_secret` | `tests/test_config.py` | `PetasosConfig(session_secret=b"key").to_dict()` has no `session_secret` key |
| `test_mint_token_rejects_null_bytes` | `tests/test_frequency.py` | `mint_token(session_id="\x00abc", host_id="h")` and `mint_token(session_id="s", host_id="h\x00x")` both raise `ValueError` |

Pre-existing tests that MUST stay green (no edit): all 29 existing tests in `tests/test_frequency.py`, which pass bare `session_id` strings with `session_secret=None` (default config). Also `test_premium_active_frequency_populates_score` and `test_frequency_hook_exception_lands_in_errors` in `tests/test_premium_integration.py`. Also all guard tests in `tests/test_guard.py` (no `session_secret` configured in existing tests).

## Test command

```
py -3.13 -m pytest tests/test_frequency.py tests/adversarial/frequency/test_session_spoofing.py tests/test_premium_integration.py tests/test_guard.py tests/test_config.py -v && py -3.13 -m pytest -q && py -3.13 -m ruff check . && py -3.13 -m ruff format --check . && py -3.13 -m mypy --strict .
```

Targeted files first (frequency + adversarial + integration + guard for `_derive_tier` regression), then full suite for no-regression, then lint+format+typecheck. `py -3.13` pins the interpreter (bare `python` is 3.10 on this Windows host, fails `requires-python>=3.11`).

---

## Done when

- [ ] `SessionToken` frozen dataclass added to `petasos/premium/frequency.py` and exported from `petasos/__init__.py`. *(brief 1)*
- [ ] `_resolve_session_id()` validates HMAC via `hmac.compare_digest` on all public tracker methods (`update`, `get_state`, `terminate_session`, `reset`). *(brief 2)*
- [ ] `session_secret: bytes | None = None` added to `PetasosConfig`; `to_dict()` excludes it; `from_dict()` accepts base64-encoded string. *(brief 3)*
- [ ] Pipeline mints tokens when secret is configured; `inspect()` signature unchanged; `host_id` property exposed. *(brief 4)*
- [ ] Guard mints tokens before calling `get_state()` when secret is configured, using public accessors. *(D9)*
- [ ] All 13 new tests pass (5 adversarial + 4 frequency unit + 1 guard + 1 pipeline integration + 2 config). *(brief 5, expanded from 7)*
- [ ] Backward compatibility confirmed: full test suite passes with `session_secret=None`. *(brief 6)*
- [ ] `py -3.13 -m ruff check .`, `py -3.13 -m ruff format --check .`, and `py -3.13 -m mypy --strict .` clean. *(brief 7)*

---

## Out of scope

- **Session ID format validation** (e.g., UUID enforcement) — separate concern. `mint_token()` rejects empty session_id but does no further format validation. *(brief)*
- **Network-level session binding** (TLS channel binding) — Petasos is in-process, no network. *(brief)*
- **Rate limiting on token validation failures** — could be added but is separate from the core fix. *(brief)*
- **Drawbridge backport** — uncoupled project, own ticket if needed. *(brief)*
- **Token expiry / rotation** — unnecessary for in-process HMAC; `session_ttl_seconds` already handles staleness. *(brief)*
- **`host_id` fingerprinting by Petasos** — consumer's responsibility per D3.
- **`copy()` preserving `session_secret`** — deliberately lost on copy per D11; callers must pass explicitly.

## Deferred (P2+)

- **Uniform error messages for token validation failures** (edge-cases/R1/F-12, P3): distinct messages for "bare string when secret configured" vs "HMAC mismatch" leak which failure mode occurred. Low priority given in-process threat model (D7).
- **Warning log when `SessionToken` passed without secret** (edge-cases/R1/F-6, P2): `_resolve_session_id` accepts `SessionToken` and skips HMAC verification when no secret is configured — silent no-op. Could log a warning, but adding a log call to a hot path for a non-error condition is debatable. Noted for future consideration.
- **Concurrency model documentation** (edge-cases/R1/F-13, P3): `FrequencyTracker` inherits the existing non-thread-safe design (single-threaded asyncio, GIL-protected under CPython). Token validation does not introduce new concurrency concerns.
- **Guard `_derive_tier` error propagation** (correctness/R3/F-1, P2): if `mint_token()` raises `ValueError` inside `_derive_tier`, the exception propagates uncaught to the `evaluate()` caller. This is fail-closed behavior (tool calls fail safely on token errors). The pipeline path swallows errors (pipeline-never-throws invariant); the guard path does not. The asymmetry is intentional — the guard is a security gate that should fail closed, not degrade silently.
- **Guard negative test** (edge-cases/R2/F-7, P3): `test_guard_derive_tier_with_session_secret` covers the happy path only. A complementary negative test (bare string rejected when secret configured) is implicitly covered by tracker-level adversarial tests but not tested at the guard integration level.
