# Edge-Cases Review — round 1

## Findings

### F-1: Runtime check breaks existing passing tests — "profile exempts a DEFAULT alias target" — P0
A profile that exempts a DEFAULT alias *target* (`tool_exempt_list=["exec"]`, empty own alias map) + a call to a DEFAULT alias *source* (`evaluate("bash")`). Proposed `_normalize_tool_name("bash")`: combined = DEFAULT (incl. `bash→exec`), `resolved="exec"`, `"exec" in {"exec"}` → fallback fires → returns `"bash"` → Step 4 `"bash" not in {"exec"}` → exempt short-circuit lost.
- `tests/test_premium_integration.py:369` `test_guard_with_profile_exempt` (exempt `exec`, call `bash`) — **breaks**.
- `tests/test_guard.py:282` `test_exempt_tool_skips_scanning` (exempt `read`, call `file_read`, `file_read→read` default) — **breaks**.
Violates Done-when "no regression". The spec's "Files to leave alone" only reasoned about built-ins shipping empty lists; never considered a custom profile exempting a default alias target. Semantic ambiguity: is suppressing `bash→exec` when `exec` is exempt desired? The existing tests encode "exempt exec, allow bash" as legitimate.
**Fix:** decide explicitly. Either (a) new behavior is correct → list those tests as updated + add a Decision; or (b) exempting a default alias target stays legal → the runtime check must fire only for the *profile's own* alias entries, not merged defaults (realigns runtime with construction, F-2).

### F-2: Construction gate and runtime gate enforce different invariants — P1
Construction (`_parse_profile`/`_merge_with_base`) intersects only the profile's OWN alias values against exempt — never `DEFAULT_TOOL_ALIASES`. Runtime uses the COMBINED map. So a profile that exempts `exec` passes construction clean, then silently behaves differently at runtime (default `bash→exec` suppressed). D1 frames the two gates as the same check at two layers; they are not (own-map vs combined-map). Contradicts D4's "operators see the problem at creation, not later."
**Fix:** make both gates enforce the identical invariant. Preferred: runtime fires only for profile-introduced aliases (`name in self._profile.tool_alias_map`), matching construction's profile-own scope. (Default aliases onto an operator-exempted target stay legal.)

### F-3: "Update existing test" instruction is non-deterministic — P2
`test_profile_alias_maps_exec_to_read_exempt` builds `ResolvedProfile` directly, so construction `ValueError` never fires for it — only the runtime branch applies. The spec's "construction raises ValueError, OR normalize=='exec'" either/or invites the wrong branch.
**Fix:** state unambiguously: this test stays direct-construction and asserts `normalize("exec")=="exec"`; the `ValueError` assertions live only in the new parse/merge tests.

### F-4: `test_default_aliases_not_in_builtin_exempt` is a tautology today — P2
All five built-ins ship empty exempt → `set() & set()` five times; can't fail until a built-in JSON is edited (intended tripwire, fine). But the LIVE risk surface is custom/runtime profiles (F-1/F-2), which this structural test doesn't exercise. False confidence.
**Fix:** keep the structural test; add a custom-profile test exercising the live path (exempt a default target + call the source; under the corrected design assert the legitimate case is preserved / the profile-own case is blocked).

### F-5: Collision `ValueError` doesn't identify which profile failed — P2
Message names colliding values but not the profile (`data["name"]` / `"custom"`). `_load_builtins` iterates five JSONs; a future built-in collision crashes with no indication which file. 
**Fix:** include the profile name: `f"profile {data.get('name','?')!r}: tool_alias_map targets cannot be exempt keys: {sorted(collisions)}"`.

### F-6: `str(v).lower()` masks non-string alias values → latent runtime AttributeError — P2
Existing validation only checks `if not v`. A list value `{"exec":["read"]}` passes; `str(["read"]).lower()` won't intersect exempt (collision check silently passes); at runtime `combined.get("exec")=["read"]` then `name.strip()` → uncaught `AttributeError` in `_normalize_tool_name` (before any try/except).
**Fix:** add `isinstance(v, str)` validation to the existing non-empty loop (rejects non-str alias values with a clear error) and intersect with `{v.lower() for v in ...}` (no `str()` coercion).

## Summary
P0: 1 | P1: 1 | P2: 4 | P3: 0 | P4: 0
Note: F-1's class breaks at least two existing tests (`test_guard_with_profile_exempt`, `test_exempt_tool_skips_scanning`).

STATUS: RED P0=1 P1=1 P2=4 P3=0 P4=0
