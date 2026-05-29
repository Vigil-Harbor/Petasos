# Edge-Cases Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: Memory-bound eviction can evict actively contributing sessions mid-window
**Severity:** P1
**Where:** spec.md:139-149 (Design section 4, memory bound enforcement)
**Edge case:** High-cardinality burst where actively alerting sessions are evicted because they have older timestamps than newer throwaway sessions
**What happens:** Attacker generates > `max_entries` throwaway sessions. The oldest-by-last-fire eviction removes legitimate sessions' tracking state. On next `evaluate`, `setdefault` creates a fresh deque, resetting the contribution count. The attacker controls which entries survive (newest always win), turning the eviction itself into an attack vector.
**Suggested fix:** After stale-key pruning removes entries with expired windows, remaining entries are all "live." If count still exceeds max_entries, rate-limit new sessions rather than evicting old ones.

### F-2: `alert_per_session_contribution_cap >= alert_per_minute_cap` renders session cap meaningless
**Severity:** P2
**Where:** spec.md:60-61, spec.md:67
**What happens:** Session cap never triggers; global cap fires first. Single session can consume all global slots. Attack unmitigated.
**Suggested fix:** Add cross-field validation: `cap < per_minute_cap`.

### F-3: Empty deque in sort key during memory-bound eviction
**Severity:** P3
**Where:** spec.md:143-144
**Note:** The `0.0` sentinel is defensive and correct. Document the intent.

### F-4: `_rate_limited_count` increment ambiguity
**Severity:** P2
**Where:** spec.md:111
**Note:** Same counter for session cap and global cap. Add separate counter for observability.

### F-5: No composite test for cooldown + session cap + global cap
**Severity:** P2
**Where:** spec.md test plan
**Note:** Three-gate composition with realistic cooldown values untested.

### F-6: `session_id` containing pipe character — existing issue, out of scope
**Severity:** P3

### F-7: No test for `cap=1` minimum configuration
**Severity:** P2
**Where:** spec.md:164-173
**Note:** Need test that cap=1 suppresses the D2 re-entry scenario.

### F-8: `_prune_stale` O(n) on every call
**Severity:** P3
**Where:** spec.md:128-148
**Note:** Performance concern at scale, not correctness.

### F-9: Spec does not address `to_dict`/`from_dict` round-trip
**Severity:** P3
**Note:** Handled automatically by dataclass fields. Informational.

### F-10: Frozen dataclass pattern verified correct
**Severity:** P4
**Note:** Confirmation, not a finding.

## Summary
P0: 0 | P1: 1 | P2: 4 | P3: 3 | P4: 1

STATUS: RED P0=0 P1=1 P2=4 P3=3 P4=1
