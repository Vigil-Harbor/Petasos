# Edge-Cases Review -- Round 1

## Findings

### F-1: TTL eviction path does not write defensive tombstones for terminated sessions (P1)
Attack: terminate S → FIFO-evict S's tombstone (via many other terminations) → TTL-expire S → `is_terminated(S)` returns False → guard allows. The `_evict_one()` path has defensive writes but TTL eviction at L142-149 does not.

### F-2: Spec contradicts brief on reset() semantics without explicit justification (P2)
Brief says reset() clears terminated state. Spec D3 says reset() preserves. Sound decision but not flagged as brief departure.

### F-3: is_terminated() accepts bare string, bypassing session token HMAC (P2)
When session_secret configured, `is_terminated()` takes bare `str` without HMAC verification, unlike `get_state()`, `update()` etc. Guard's internal use is safe but public API surface allows untrusted probing.

### F-4: Empty string session_id not validated (P3)
`is_terminated("")`, `force_reset("")`, `guard.evaluate(..., "")` all silently accept empty strings.

### F-5: No test for tombstone FIFO cap interaction with TTL eviction (P2)
The attack from F-1 has no test coverage. Tests cover TTL and FIFO independently but not combined.

### F-6: Tombstone sentinel score not historical (P3)
Same as correctness F-5. Informational.

### F-7: _evict_one() O(n) linear scan (P4)
Performance concern, not correctness. Out of scope.

## Summary
P0: 0 | P1: 1 | P2: 3 | P3: 2 | P4: 1

STATUS: RED P0=0 P1=1 P2=3 P3=2 P4=1
