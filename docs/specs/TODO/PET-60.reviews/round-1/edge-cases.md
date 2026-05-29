# Edge-Cases Review — Round 1

### F-1 (P1): `syntactic_error` bypassed by `ml_total == 0` early return
Same as correctness F-1. Common deployment (MinimalScanner only, no ML scanners) silently ignores MinimalScanner errors.

### F-2 (P2): Missing consecutive-backslash test case for JSON depth state machine
Test plan covers `\"` but not `\\\\` sequences. The state machine handles them correctly but no regression test exists for the most subtle case.

### F-3 (P2): Removing _resolve_overlaps breaks existing tests and direct callers
`test_overlapping_manual_path_deduplicates` asserts the old behavior. Spec's test #14 contradicts existing test.

### F-4 (P2): NaN floats bypass confidence clamp
`max(0.0, min(1.0, float('nan')))` returns `nan`. `inf` and `-inf` are handled correctly.

### F-5 (P3): No early exit for depth check on oversized payloads
Not a regression — existing code has same behavior.

### F-6 (P3): scanner_name magic string fragility
Pre-existing technical debt, not a regression.

### F-7 (P4): NUL byte regex — non-issue in CPython

### F-8 (P3): anonymize() docstring update not specified

P0: 0 | P1: 1 | P2: 2 | P3: 3 | P4: 1

STATUS: RED P0=0 P1=1 P2=2 P3=3 P4=1
