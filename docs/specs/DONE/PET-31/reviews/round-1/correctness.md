# Correctness Review — Round 1

## Findings

### F-1 (P1): Pipeline `__init__` signature drops `on_audit`/`on_alert` and changes `scanners` type
Spec Change 4 code block shows `scanners: list[Scanner] | None = None` but actual code is `Sequence[Scanner] = ()`. Also omits `on_audit` and `on_alert` callback parameters.

### F-2 (P2): Scope names helper `_verify_session` but Design uses `_resolve_session_id`
Naming inconsistency between spec sections.

### F-3 (P2): Claims "28 tests" in nonexistent `TestFrequencyTracker` class
Should be "29 tests across 8 test classes".

### F-4 (P4): Grounding commit hash stale
`a920d3f` vs actual HEAD. Files unchanged — cosmetic.

### F-5 (P3): Guard accesses private `_host_id` and `_session_secret` across class boundaries
Should use public properties/accessors.

### F-6 (P3): `to_dict()`/`from_dict()` round-trip for `bytes` not JSON-safe
`session_secret: bytes` breaks `json.dumps(config.to_dict())`.

STATUS: RED P0=0 P1=1 P2=2 P3=2 P4=1
