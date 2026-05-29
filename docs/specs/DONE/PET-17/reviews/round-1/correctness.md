# Correctness Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: Spec "Files to leave alone" mislabels L93-96 as "Critical alert path"
**Severity:** P4
**Where:** spec.md:24
**Claim:** "Critical alert path in `alerting.py` (L93-96, L122-129) -- PET-16 scope"
**Why this is wrong:** L93-96 is the loop setup shared by both critical and non-critical paths. The actual critical path behavior is the implicit else of L97's `if not is_critical:`. The characterization is imprecise but the intent ("don't touch these lines") is clear and does not affect implementation.
**Suggested fix:** Change to: "Critical alert path infrastructure in `alerting.py` (L93-96 loop setup, L122-129 alert acceptance + callback) -- PET-16 scope"

### F-2: Shared `_rate_limited_count` for session-cap and global-cap events reduces observability
**Severity:** P3
**Where:** spec.md:111
**Claim:** `self._rate_limited_count += 1` when a session hits its per-session contribution cap
**Why this is wrong:** Reuses the same counter for both session-contribution-cap and global cap rejections. Operators cannot distinguish the two. The brief does not require separate counters.
**Suggested fix:** Consider adding `_session_rate_limited_count` property or note the shared counter is intentional.

### F-3: Brief's "default: 10" for `alert_per_minute_cap` is factually wrong (actual: 5) but spec correctly avoids propagating it
**Severity:** P4
**Where:** Brief line 22 vs config.py:53
**Note:** The spec uses ratio-based formulas instead of hardcoded numbers, correctly sidestepping the brief's error.

### F-4: Spec does not specify where new config fields should be placed
**Severity:** P4
**Where:** spec.md:57-62
**Suggested fix:** Add: "Place in the existing 'Alerting thresholds' section, after `alert_ring_buffer_capacity`."

### F-5: Memory bound can temporarily exceed by up to 5 entries per `evaluate()` call
**Severity:** P3
**Where:** spec.md:123-149
**Note:** `_prune_stale()` runs at the start; new entries appended during the candidate loop. Overshoot of ~5 entries corrected on next call.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 2 | P4: 3

STATUS: GREEN
