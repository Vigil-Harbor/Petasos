# Correctness Review — PET-75 Round 2

## Closure of round 1 findings
All round 1 findings (correctness F-1 through F-5, edge-cases F-1 through F-12, conventions F-1 through F-7) CLOSED with evidence.

## Findings

### F-1: `_compact_ttl_deque` produces an unsorted deque, breaking the eviction loop invariant
**Severity:** P0
The compaction helper iterates `self._sessions.items()` in dict insertion order, not by `last_update`. After compaction, the deque may have a later-expiring entry before an earlier-expiring one, causing the eviction loop to stop early and leave expired sessions stranded.

### F-2: `_premium_frequency_hook` code block has redundant `frequency_enabled` check
**Severity:** P2
`_check_premium("frequency")` already checks `frequency_enabled` via `_FEATURE_GATES`. Inherited from current code. Not a bug.

### F-3: `_standalone_tier3_check` is trivially safe — cannot raise
**Severity:** P3
Academic: the function is a pure sum over a generator. No action needed.

## Summary
P0: 1 | P1: 0 | P2: 1 | P3: 1 | P4: 0

STATUS: RED P0=1 P1=0 P2=1 P3=1 P4=0
