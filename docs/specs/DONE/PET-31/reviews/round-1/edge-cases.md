# Edge-Cases Review — Round 1

## Findings

### F-1 (P1): `bytes` field breaks `to_dict()` JSON serialization
`session_secret: bytes` in PetasosConfig → `to_dict()` → `json.dumps()` crashes with TypeError.

### F-2 (P1): Guard accesses `self._pipeline._host_id` — no attribute exists today + no guard-level test
Change 5 modifies guard.py but no guard-level tests exercise the new token-minting behavior.

### F-3 (P2): Guard accesses `_session_secret` private attribute cross-object
Should use a public `requires_token` property.

### F-4 (P2): Empty `session_id` string passes HMAC validation
`mint_token("", host_id)` produces valid token for empty key. Need `if not session_id` guard.

### F-5 (P2): HMAC message `session_id:host_id` has delimiter collision
`"a:b" + "c"` == `"a" + "b:c"`. Use null-byte separator.

### F-6 (P2): `_resolve_session_id` accepts `SessionToken` when no secret — silent no-op
HMAC is never verified if secret not configured. Should log a warning or document.

### F-7 (P2): `SessionToken` not added to `__init__.py` exports
Missing from package public API.

### F-8 (P2): No test for Pipeline constructor ValueError (secret without host_id)
Missing regression test for construction-time guard.

### F-9 (P2): `mint_token` ValueError gets swallowed by pipeline exception handler
Should document this degradation path.

### F-10 (P2): Pipeline `scanners` type changed in spec vs actual
`list[Scanner] | None` vs `Sequence[Scanner] = ()`.

### F-11 (P3): No test for `mint_token` when `session_secret is None`
Missing coverage for error branch.

### F-12 (P3): Timing side-channel in distinct error messages
Different errors for bare string vs bad HMAC. Low priority for in-process.

### F-13 (P3): No concurrency test for `update()` with tokens
Inherits existing non-thread-safe design.

STATUS: RED P0=0 P1=2 P2=6 P3=3 P4=0
