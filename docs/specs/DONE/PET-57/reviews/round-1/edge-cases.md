# Edge-Cases Review -- round 1

## Findings

### F-1: Attack scenario in brief does not reach `_parse_profile` -- spec silently inherits incorrect call-path claim
**Severity:** P2
**Where:** spec.md:11 (Goal section), brief:22
`ProfileResolver.resolve(dict)` dispatches to `_merge_with_base`, not `_parse_profile`. The spec correctly identifies `_merge_with_base` as safe but does not clarify that the normal public API path is already safe. Fix targets `_parse_profile` as defense-in-depth for direct callers.

### F-2: Test 2 mutates `data["tool_alias_map"]` but `_parse_profile` rebuilds alias_map via a comprehension -- test might pass without the fix
**Severity:** P2
**Where:** spec.md:88 (Test #2)
The existing comprehension on L98 already creates `alias_map` as a fresh dict. Test 2 would pass even WITHOUT the proposed `dict(alias_map)` change, making it a non-diagnostic regression test for that specific change. The spec acknowledges the redundancy in Decision 4 but does not account for how this affects Test 2's diagnostic value.

### F-3: Spec does not address `ResolvedProfile` direct construction bypass
**Severity:** P3
**Where:** spec.md:112-118 (Out of scope)
A caller can construct `ResolvedProfile(severity_overrides=MappingProxyType(attacker_dict), ...)` directly, bypassing `_parse_profile`. The same retained-reference vulnerability exists at this layer.

### F-4: Test 3 (`test_empty_overrides_not_shared`) relies on CPython dict identity behavior
**Severity:** P4
`data.get("severity_overrides", {})` evaluates `{}` freshly each time (not a mutable default argument). `MappingProxyType` always creates distinct proxy objects. Test would likely pass without the fix.

### F-5: `_parse_profile` is underscore-prefixed but tests import it directly
**Severity:** P4
Existing pattern in `test_profiles.py:13` and `test_profiles_suppress.py:11`. No convention violation.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 1 | P4: 2

STATUS: GREEN
