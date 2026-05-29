# Correctness Review -- round 2

## Closure of round 1 findings

All round 1 findings CLOSED:
- F-1 (P1): `profiles/__init__.py` import now only imports `_UNSUPPRESSIBLE_RULE_IDS` (spec L84-97)
- F-2 (P2): "Tests NOT added" table notes caplog gap as "acceptable coverage gap" (L217)
- F-3 (P2): Code blocks annotated with L11/L13/L15 line markers (L86-96)

## Findings

### F-1: Proposed xfail reason for `test_rt075_chain_pre_fix_baseline` includes SYN-08 as a cause, contradicting spec's own analysis
**Severity:** P2
Spec L107 says "SYN-08 does not change this test's behavior" but L225 proposes reason mentioning SYN-08 as a fix cause.
**Suggested fix:** Rephrase to either document which chain links are fixed (not which caused the failure) or drop SYN-08 from the attribution.

### F-2: Test command uses hardcoded Windows Python path
**Severity:** P4

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 0 | P4: 1

STATUS: GREEN
