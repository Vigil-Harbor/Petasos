# PET-35 Correctness Review — Round 1

## Findings

### F-1: Duplicate test between renamed existing test and new test 4 (P3)
The spec renames `test_whitespace_stripped_after_alias_lookup` to `test_whitespace_stripped_before_alias_resolves` with assertion `" bash "` → `"exec"`, and separately adds new test 4 `test_whitespace_before_alias_now_resolves` with the same input and output. Both tests are in the same file and verify the same behavior.

### F-2: casefold/lower mismatch between guard.py runtime GUARD-03 check and profiles.py construction-time check (P3)
The spec changes GUARD-03 runtime check to `casefold()` while `profiles/__init__.py` L79/L82 still use `.lower()`. For ASCII (the practical case), these are identical. For non-ASCII (German eszett etc.), they diverge. A defense-in-depth inconsistency, not a practical exploit.

### F-3: Spec line reference "L173" is ambiguous (P4)
"L173" in the key changes list refers to the current code's line number while describing the proposed change. Minor labeling nit.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 2 | P4: 1

STATUS: GREEN
