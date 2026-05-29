# Edge-Cases Review -- Round 2

## Closure of round 1 findings

All 7 round-1 edge-case findings closed. Cross-lens closure verified for all 20 findings across all three lenses.

## Findings

### F-1: Files-changed table doesn't distinguish PET-30 shipped vs PET-34 pending (P2)
Scope table lumps all changes in one row. Done When correctly uses checked/unchecked but table is ambiguous.

### F-2: Adversarial test count inconsistency -- spec body says 8 but table lists 9 (P3)
Test 8 (new D7 test) added to table but line 205 still says "8 adversarial". Should be 9.

### F-3: Bulk TTL eviction may compete for tombstone slots under small caps (P2)
Multiple terminated sessions expiring at once and competing for tombstone cap is inherent to bounded design. Not a regression but undocumented.

### F-4: is_terminated() token-free not cross-referenced in Layer 2 pseudocode (P3)
D8 documents the rationale but Layer 2 design section doesn't reference it.

### F-5: Thread safety not mentioned (P3)
FrequencyTracker is not thread-safe. asyncio single-threaded event loop is the expected model.

### F-6: _evict_one() no-candidate edge case (P3)
If only the protected ID exists, max_sessions temporarily exceeded by 1.

### F-7: D7 pseudocode accesses _sessions[sid] after constructing stale list (P4)
Safe but fragile to future modification.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 4 | P4: 1

STATUS: GREEN
