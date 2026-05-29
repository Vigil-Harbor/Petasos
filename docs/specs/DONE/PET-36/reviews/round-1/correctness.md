# Correctness Review — round 1

## Findings

### F-1: `Grounded against` HEAD `d927f4b` is stale; repo HEAD is `d0af5aa` — P3
guard.py/profiles/test_tool_smuggling.py were last touched in `d927f4b`, and intervening merges (`44639fe` etc.) didn't move them, so every line citation is still accurate. Cosmetic. Update line 5 to note HEAD `d0af5aa` (files unchanged since `d927f4b`).

### F-2: Runtime backstop doesn't cover mixed-case exempt on the direct-construction path — P2
`tool_exempt_list` is only lowercased inside `_parse_profile`/`_merge_with_base` (L85,144). A directly-built `ResolvedProfile(tool_exempt_list=frozenset({"Read"}), tool_alias_map={"exec":"Read"})`: runtime `resolved.lower()="read" in {"Read"}` → False → fallback doesn't fire; Step 4 (`guard.py:114`, no lowercasing) matches `"Read" in {"Read"}` → exempt bypass. Canonical lowercase exploit is fully closed; mixed-case-on-direct-construction survives.
**Fix:** runtime check compares against a lowercased exempt set: `resolved.lower() in {e.lower() for e in self._profile.tool_exempt_list}`.

### F-3: Full-`evaluate()` test will short-circuit at the premium gate (Step 0) — P2
`evaluate()` returns `_PREMIUM_INACTIVE` when `is_premium_active("tool_guard")` is False (guard.py:86). The `test_tool_smuggling.py` helpers build a pipeline with no license, so `test_alias_exec_to_read_exempt_blocked` never reaches Step 4; `reason` would be `"premium inactive"` and the weak `reason != "tool exempt per profile"` assertion passes for the wrong reason (false green).
**Fix:** the test must force `is_premium_active("tool_guard")` True (monkeypatch or inject a valid test license) and assert positively (params inspected / `reason` is an allow-or-block reason, not `"premium inactive"`).

### F-4: New tests need imports not present in the target files — P3
`tests/test_profiles.py` doesn't import `_parse_profile`; `tests/test_guard.py` doesn't import `DEFAULT_TOOL_ALIASES`/`ProfileResolver`. Trivial additions; note them in the Test plan.

## Verification (grounding confirmed)
- guard.py: `_normalize_tool_name` L155-168, combined map L162, Step 4 exempt L113-121 (L114 `normalized_name in tool_exempt_list`), `DEFAULT_TOOL_ALIASES` targets `{exec,read,write,browser}` L21-34, empty-name block L91-98, `_logger` L12. Change 3 snippet compiles.
- profiles/__init__.py: `_parse_profile` L63-87 (alias_map L73, exempt lowercased L85, alias MappingProxyType L86); `_merge_with_base` L90-165 (exempt L139-144, alias L146-154, return L156); `ResolvedProfile` public frozen dataclass L22-31 (confirms D1 direct-construction premise).
- Canonical exploit (`read`/`read`): construction `{"read"}&{"read"}` → ValueError; runtime fallback fires → `"exec"` → Step 4 miss → param scan. Both gates stop it.
- All 5 built-in JSONs ship empty `tool_exempt_list`/`tool_alias_map` (spec L27 + D6 accurate; structural test green on landing).
- `tests/unit/**` does NOT exist (D5 correct); flat files exist; `test_profile_alias_maps_exec_to_read_exempt` at `test_tool_smuggling.py:39` asserting `normalize("exec")=="read"`.
- All 7 brief Done-when map 1:1.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 2 | P4: 0

STATUS: GREEN
