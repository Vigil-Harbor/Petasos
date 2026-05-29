# Conventions Review — Round 1

## Findings

### F-1 (P2): Internal name inconsistency `_verify_session` vs `_resolve_session_id`
### F-2 (P2): Guard accesses `self._pipeline._host_id` — breaks encapsulation pattern
### F-3 (P2): `SessionToken` not mentioned in `__init__.py` exports
### F-4 (P2): `PetasosConfig.to_dict()` broken for `bytes` field
### F-5 (P3): No `__post_init__` validation for `session_secret` type
### F-6 (P2): Guard accesses `_session_secret` — should use `self._config.session_secret`
### F-7 (P3): Pipeline constructor backward compat — fine, default value
### F-8 (P3): `host_id` as Pipeline param — spec addition with rationale (D3), OK
### F-9 (P3): D9 Guard minting — spec addition with rationale, OK
### F-10 (P2): Pipeline `scanners` type mismatch in spec code block

STATUS: GREEN
