# PET-30 Edge-Cases Review — Round 3

## Closure of round 2 findings
All round-2 edge-cases findings (F-1 through F-6) confirmed CLOSED.

## Findings

### F-1: Tombstone early-return produces spurious tier-escalation alerts on every call
**Severity:** P1
**Where:** spec Design section 4
Tombstone early-return uses `previous_score=0.0`. AlertManager._check_tier_escalation() computes `evaluate_tier(0.0)` = `"none"`, which differs from tier="tier3", firing an escalation alert on every `update()` call for a tombstoned session.
**Suggested fix:** Use `self._config.tier3_threshold` for both `previous_score` and `current_score` in the tombstone early-return. This ensures `evaluate_tier()` returns `"tier3"` for both, preventing spurious alerts.

### F-2: Audit records `session_score=0.0` for tombstoned tier3 sessions
**Severity:** P2
`0.0` is internally inconsistent with tier3. Fixed by using `tier3_threshold` as the sentinel score.

### F-3: No test for alerting behavior with tombstone early-return
**Severity:** P2
Test plan doesn't exercise the pipeline-level alerting path for tombstoned sessions.

## Summary
P0: 0 | P1: 1 | P2: 2 | P3: 0 | P4: 0

STATUS: RED P0=0 P1=1 P2=2 P3=0 P4=0
