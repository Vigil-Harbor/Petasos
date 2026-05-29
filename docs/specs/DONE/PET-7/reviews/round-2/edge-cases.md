# Edge-Cases Review -- round 2

## Closure of round 1 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| edge-cases | F-1 | premium_features dict mutable on frozen PipelineResult | CLOSED | spec section 5.5 uses `MappingProxyType[str, str] | None` |
| edge-cases | F-2 | PipelineResult rebuild at stage 12 drops premium fields | CLOSED | `_build_result()` helper covers both sites |
| edge-cases | F-3 | Dict mutation during iteration in eviction loop | CLOSED | Two-pass collect-then-delete |
| edge-cases | F-4 | _creation_timestamps deque never pruned | CLOSED | Pruning before rate-limit check |
| edge-cases | F-5 | DISABLED_RESULT and RATE_LIMITED_RESULT identical | CLOSED | Deferred as P2 with object identity convention |
| edge-cases | F-6 | Escalation hook imports evaluate_tier but never calls it | CLOSED | Import removed |
| edge-cases | F-7 | Frozen dataclass needs object.__setattr__ | CLOSED | Pattern shown |
| edge-cases | F-8 | frequency_weights glob key convention | CLOSED | Deferred as P2 |
| edge-cases | F-9 | Empty finding_types as decay heartbeat | CLOSED | Deferred as P3 |
| edge-cases | F-10 | Tier 3 termination doesn't force safe=False | CLOSED | D11 decision |
| edge-cases | F-11 | FrequencyTracker always constructed in OSS | CLOSED | Deferred as P3 |
| edge-cases | F-12 | >= vs > threshold comparison | CLOSED | D10 decision |
| edge-cases | F-13 | tier field as bare str | CLOSED | Deferred as P2 |
| edge-cases | F-14 | No test for frequency hook error | CLOSED | Added to test plan |
| edge-cases | F-15 | math.exp overflow guard | CLOSED | Clamp added |

## Findings

### F-1: Empty `frequency_weights={}` silently disables scoring
**Severity:** P2
**Where:** spec section 5.3
**Edge case:** `frequency_weights={}` passes validation but all weights resolve to 0.0, silently disabling scoring.
**Suggested fix:** Add validation: empty dict raises ValueError, or document that `{}` means "no weights" intentionally.

### F-2: Eviction by oldest allows attacker to evict high-suspicion sessions
**Severity:** P2
**Where:** spec section 5.1, steps 2-3
**Edge case:** Eviction prefers terminated then oldest, but not by suspicion score. An attacker creating new sessions steadily evicts legitimate high-suspicion sessions.
**Suggested fix:** Note as known limitation or add score to eviction preference.

### F-3: `_match_weight` glob stripping convention not specified in constructor
**Severity:** P2
**Where:** spec section 5.1
**Edge case:** Constructor "pre-partitions" but does not specify how glob keys are identified or how `".*"` is stripped.
**Suggested fix:** Add explicit partitioning rule for glob detection and prefix extraction.

### F-4: `MappingProxyType` not JSON-serializable via `dataclasses.asdict()`
**Severity:** P2
**Where:** spec section 5.5
**Edge case:** `json.dumps(dataclasses.asdict(result))` raises TypeError for `MappingProxyType`.
**Suggested fix:** Document serialization workaround or add `to_dict()` method.

### F-5: Third PipelineResult construction site (outer exception handler)
**Severity:** P1
**Where:** spec section 5.4 vs `pipeline.py` lines 178-187
**Edge case:** Outer `inspect()` exception handler creates PipelineResult with `None` premium fields even when premium is active. The spec says "Both construction sites" but there are three.
**Suggested fix:** Acknowledge the third site and state that `None` defaults are intentional for catastrophic failures.

### F-6: Rate limit interaction with TTL eviction
**Severity:** P3
**Where:** spec section 5.1, steps 1-2
**Edge case:** TTL eviction in step 1 usually reduces session count below max_sessions, making rate limit in step 2 almost never trigger under normal conditions.
**Suggested fix:** Note as intentional: rate limit is a flood-protection backstop.

### F-7: Rolling window pruning only runs when finding_types is non-empty
**Severity:** P2
**Where:** spec section 5.1, step 8
**Edge case:** Empty-finding updates (decay heartbeats) don't prune stale rolling entries, leaving tier elevated.
**Suggested fix:** Move pruning outside the `if finding_types` guard.

### F-8: Rate limit window hardcoded to 60 seconds
**Severity:** P3
**Where:** spec section 5.1, step 2
**Suggested fix:** Extract as module constant `_RATE_LIMIT_WINDOW_SECONDS = 60`.

### F-9: `finding_types` parameter naming — receives rule_ids not finding types
**Severity:** P2
**Where:** spec section 5.4
**Suggested fix:** Rename to `rule_ids` in both hook and tracker API.

### F-10: No test for `clear()` resetting `_creation_timestamps`
**Severity:** P3
**Where:** spec test plan
**Suggested fix:** Add one line to design: "`clear()` removes all sessions and all creation timestamps."

## Summary
P0: 0 | P1: 1 | P2: 6 | P3: 3

STATUS: RED P0=0 P1=1 P2=6 P3=3
