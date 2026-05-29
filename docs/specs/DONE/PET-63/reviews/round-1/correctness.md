# Correctness Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: _HmacSha256Operator is not directly importable -- test plan unimplementable as written (P1)
Tests 4 and 5 call `_HmacSha256Operator().validate(...)` directly, but the class is defined inside `_make_hmac_operator_class()` at L61 and cannot be imported as a module-level symbol. Tests must call `_make_hmac_operator_class()` to obtain the class.

### F-2: Layer 4 uses `assert` for a security invariant -- stripped by Python `-O` (P2)
`assert hash_key` in `_anonymize_engine_path()` is defense-in-depth but disappears under `python -O`. Replace with `if not hash_key: raise AssertionError(...)` or `ValueError(...)`.

### F-3: Spec's "Before" code block for Layer 4 omits enclosing `elif mode == "hash":` context (P3)
The code block shows the inner `if/else` without the enclosing branch. Adding the `elif` line would anchor the replacement precisely.

## Summary
P0: 0 | P1: 1 | P2: 1 | P3: 1

STATUS: RED P0=0 P1=1 P2=1 P3=1
