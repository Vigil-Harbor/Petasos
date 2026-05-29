# Edge-Cases Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

F-1 (P0): `copy.deepcopy(config)` crashes on `MappingProxyType` in `frequency_weights`. Suggested: use `dataclasses.replace(config)` — preserves all fields including session_secret, works with slots.

F-2 (P2): `evaluate_tier()` raising `ValueError` corrupts `FrequencyTracker` session state — rolling window is updated before the raise. Suggested: return fail-secure "tier3" instead of raising.

F-3 (P2): `_HARDCODED_TIER3_FLOOR` is a module variable, not a literal constant — still mutable. Suggested: use inline literal `30.0`.

F-4 (P2): Test 11 brittle — `typing.get_type_hints()` + `Final` detection is version-dependent.

F-5 (P3): `config.copy()` method still loses `session_secret` — existing bug not addressed.

F-6 (P3): `_compute_safe()` fallback has no logging — silent behavior change.

F-7 (P4): Test 10 calls private `_compute_safe` directly — acceptable for security tests.

## Summary
P0: 1 | P1: 0 | P2: 3 | P3: 2 | P4: 1

STATUS: RED P0=1 P1=0 P2=3 P3=2 P4=1
