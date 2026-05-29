# Edge-Cases Review -- round 2

## Closure table
All round 1 P0/P1/P2 findings CLOSED. See agent output for full closure table.

## Findings
F-1 (P2): evaluate_tier guard returns "tier3" silently — no logging. Suggest adding _logger.warning in escalation.py.
F-2 (P3): _compute_safe code snippet implies duplicate logger/import — should note existing imports in pipeline.py.
F-3 (P3): _validate_tier_thresholds still reads mutable TIER3_FLOOR — runtime guard is defense, but construction-time validation bypassed.
F-4 (P3): dataclasses.replace is shallow — relies on __post_init__ wrapping all mutable fields immutable.
F-5 (P2): Test 7 must use monkeypatch or try/finally to restore TIER3_FLOOR — spec description doesn't specify.
F-6 (P4): fail_mode parameter reassignment obscures tracing.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 3 | P4: 1

STATUS: GREEN
