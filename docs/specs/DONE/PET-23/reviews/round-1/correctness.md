# Correctness Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

F-1 (P0): `copy.deepcopy(config)` crashes when `frequency_weights` is set — `MappingProxyType` is not picklable. Suggested: use `dataclasses.replace(config)` instead.

F-2 (P1): Stale line-number anchor for pipeline session_secret workaround (says "line 166", actual code is elsewhere). Remove hardcoded line references.

F-3 (P2): Brief "Done when" criterion divergence not explicitly flagged as deviation in spec's Done-when section.

F-4 (P2): Test 11 (`get_type_hints` for `Final`) is fragile across Python versions and underspecified.

F-5 (P3): Guard.py naming imprecision — says `derive_tier()` but actual method is `_derive_tier()`.

F-6 (P3): Unaddressed impact on `evaluate_tier` callers when raising `ValueError` — ToolCallGuard.evaluate() does not catch exceptions.

## Summary
P0: 1 | P1: 1 | P2: 2 | P3: 2

STATUS: RED P0=1 P1=1 P2=2 P3=2
