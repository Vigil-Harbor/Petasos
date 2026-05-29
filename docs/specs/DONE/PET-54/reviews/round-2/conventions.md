# Conventions Review -- round 2

## Closure table
All round 1 findings CLOSED:
- conventions F-1 (duplicated prefix): CLOSED — profiles imports _STRUCTURAL_RULE_IDS; pipeline uses prefix + test 11 tripwire
- conventions F-2 (PET-59 interaction): CLOSED — Decision 7 added
- conventions F-3 (ValueError vs pipeline never throws): CLOSED — spec line 151 traces the path explicitly
- conventions F-4 (test file placement): CLOSED — acceptable in existing test_profiles.py
- conventions F-5 (brief divergence callout): CLOSED — Decision 3 explicitly notes divergence
- conventions F-6 (test 6 validates existing behavior): CLOSED — acceptable as regression test
- conventions F-7 (no sync tripwire): CLOSED — test 11 added

## Findings

### F-1: License activation pattern diverges from codebase convention (P2)
Spec proposes monkeypatching `_license_state`/`_license_claims`. Codebase convention (70+ uses) is `valid_key` fixture + `pipe.activate(valid_key)`. Spec should use the established pattern.

### F-2: `_SEVERITY_RANK` duplication not acknowledged (P3)
Existing tech debt duplicated in pipeline.py and alerting.py. PET-54 adds a new consumer. Should note in Out of Scope.

### F-3: Silent addition — `_check_severity_values` helper (P3)
Not in brief. Decision 6 provides rationale. Authorized.

### F-4: Silent addition — test 6 suppress_rules regression (P3)
Not in brief. Decision 5 boundary. Authorized.

### F-5: Silent addition — Decision 7 PET-59 interaction (P3)
Not in brief. Added for round 1 fix. Authorized.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 4 | P4: 0

STATUS: GREEN
