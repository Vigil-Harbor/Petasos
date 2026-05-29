# Edge-Cases Review — round 2

## Closure of round 1 findings
- F-1 (P0) — CLOSED: Change 3 gates on `name in self._profile.tool_alias_map`; `test_guard_with_profile_exempt` (test_premium_integration.py:369) and `test_exempt_tool_skips_scanning` (test_guard.py:282) use empty own alias maps → condition False → default alias resolves → Step 4 exempt preserved. Traced both green. Spec lists both must-stay-green (L170) + adds `test_default_alias_onto_exempt_still_allowed`.
- F-2 (P1) — CLOSED: both gates profile-own (construction intersects profile/merged alias values only; runtime keys on profile map). D1/D8 state the same invariant.
- F-3/F-4/F-5/F-6 — CLOSED (unambiguous existing-test update; live-path test added; profile-named ValueError; isinstance guard).
- correctness F-1/2/3/4, conventions F-2 — CLOSED; conventions F-1 — deferred w/ rationale.

## New-edge probes (all resolve correctly)
- (a) Re-declared default alias `{"bash":"exec"}`+exempt exec → construction ValueError (now profile-own); see F-1 below (P3 doc note).
- (b) Non-default `{"deploy":"read"}`+exempt read → blocked (GUARD-03 class). ✓
- (c) Merge base (general/admin) ships empty alias → no foreign alias injected into merged `alias`. ✓
- (d) isinstance(v,str): no existing JSON/test passes non-str alias value; `test_tool_alias_map_empty_value_raises` matches "non-empty" substring, preserved. ✓
- (e) Grep: only collision-bearing alias+exempt co-occurrence is the test being updated. ✓

## Findings

### F-1: Re-declaring a default identity alias while exempting its target is rejected at construction (D8 boundary) — P3
`{"bash":"exec"}`+exempt `exec` raises ValueError, while the semantically-identical config that omits the redundant alias (relying on the default) is legal per D8. Consistent with the profile-own invariant and fails loud, but non-obvious operator-facing behavior.
**Fix:** add one sentence to D8 naming this (redeclaring a default identity alias onto an exempted target is rejected; drop the redundant redeclaration). No code change.

### F-2: `test_tool_alias_map_empty_value_raises` (test_profiles.py:241) depends on the message keeping the "non-empty" substring — P3
New message "tool_alias_map values must be non-empty strings" preserves the substring (green). But this pre-existing test isn't in the must-stay-green list, so a future reword has no tripwire.
**Fix:** add `test_tool_alias_map_empty_value_raises` to the must-stay-green line, noting the message must retain `non-empty`.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 2 | P4: 0

All round-1 P0/P1/P2 genuinely closed (traced against real source + full suite grep). Two P3s are doc/tripwire hardening, non-blocking.

STATUS: GREEN
