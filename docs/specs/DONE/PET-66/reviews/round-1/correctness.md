# Correctness Review -- round 1

## Findings

### F-1: Spec test #6 renames brief's test (P3)
Spec names it `test_role_trigger_double_space`; brief says `test_role_switch_double_space`. Minor naming inconsistency.

### F-2: Spec test #7 input diverges from brief — improvement (P4)
Spec adds trigger to make role-switch-capability path functional. Brief's `"no  restrictions"` alone wouldn't trigger the detection path.

### F-3: Spec test #9 ReDoS input includes "previous" not in brief (P4)
More thorough than brief's version. Exercises partial match path.

### F-4: Python `\s` and `\x85` claim could be more precise (P4)
Technically correct but reads as exhaustive list when it's not.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 1 | P4: 3

STATUS: GREEN
