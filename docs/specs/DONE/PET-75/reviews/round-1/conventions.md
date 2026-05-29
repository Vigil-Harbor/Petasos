# Conventions Review — PET-75 Round 1

## Findings

### F-1: Missing `__init__.py` for new test directory `tests/adversarial/escalation/`
**Severity:** P2
Existing pattern: every `tests/adversarial/` subdirectory has `__init__.py`.

### F-2: Existing test `test_rate_limited_result_is_frozen` will break
**Severity:** P1
`tests/test_frequency.py:475` asserts `tier == "none"`. Self-contradicts spec's own "Existing frequency and escalation tests still pass" criterion.

### F-3: Brief "Done when" criterion dropped without acknowledgment — pipeline log distinction
**Severity:** P2
Brief line 38: "Pipeline log output distinguishes rate-limited from disabled." Spec drops this without rationale.

### F-4: `derive_tier()` not added to `premium/__init__.py` re-exports
**Severity:** P3
`evaluate_tier` is re-exported from `premium/__init__.py`. New sibling `derive_tier` should follow same pattern or be named with underscore.

### F-5: Hardcoded threshold contradicts brief's "configurable" direction
**Severity:** P3
Brief says "configurable, default 3". Spec hardcodes. Has rationale — flagging for human drift-check.

### F-6: `"rate_limited"` is a novel tier value with no exhaustive-match safety
**Severity:** P3
`_TIER_ACTIONS` and alerting `severity_map` don't include `"rate_limited"`. Silent fallthrough.

### F-7: FREQ-05 deque unbounded growth
**Severity:** P3
No compaction trigger. Long-lived sessions accumulate stale entries.

## Summary
P0: 0 | P1: 1 | P2: 2 | P3: 3 | P4: 0

STATUS: RED P0=0 P1=1 P2=2 P3=3 P4=0
