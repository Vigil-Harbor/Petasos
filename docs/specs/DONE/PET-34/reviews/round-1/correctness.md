# Correctness Review -- Round 1

## Findings

### F-1: Spec diverges from brief on reset() behavior without marking it as explicit override (P2)
D3 says `reset()` preserves tombstones; brief says `reset()` clears terminated state. The spec's mapping table silently reinterprets the brief's test without noting the semantic reversal.

### F-2: Spec's is_terminated() pseudocode logic differs from actual implementation (P2)
Pseudocode falls through to `_terminated_ids` check when session is in `_sessions` but `terminated=False`. Actual code returns `state.terminated` directly. Pseudocode would produce wrong behavior for a non-terminated live session with a stale tombstone.

### F-3: Spec's _derive_tier() pseudocode includes dead code not in actual implementation (P3)
`if state.terminated: return "tier3"` after `get_state()` is unreachable — `is_terminated()` already catches this case.

### F-4: Test count mismatch: spec says 21, actual is 25 (P3)
`TestConfigMaxTerminatedTombstonesValidation` has 5 sub-tests, not 1. Total: 17 unit + 8 adversarial = 25.

### F-5: D5 sentinel score is synthetic, not historical (P3)
Informational — design is sound and test 7a verifies no spurious alert.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 3

STATUS: GREEN
