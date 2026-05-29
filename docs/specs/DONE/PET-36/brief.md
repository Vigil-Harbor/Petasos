# PET-36 — GUARD-03: Forbid Aliasing onto Exempt Keys

**Plane:** PET-36 · **Finding:** GUARD-03 · **Priority:** Urgent  
**OWASP:** ASI02 — Tool-use manipulation  
**Parent:** PET-14 · **Blocks:** PET-12 (release)  
**Status:** Backlog → ready-for-dev

---

## Problem

`ToolCallGuard._normalize_tool_name` merges `DEFAULT_TOOL_ALIASES` with `profile.tool_alias_map` at L161–165 of `petasos/premium/guard.py`. Profile aliases *override* defaults via `{**DEFAULT_TOOL_ALIASES, **profile.tool_alias_map}`. After aliasing, `evaluate()` checks the resulting name against `profile.tool_exempt_list` at L113–121.

A malicious or misconfigured profile can set `tool_alias_map: {"exec": "read"}` and `tool_exempt_list: ["read"]`. Result: a call to `exec` (shell execution) resolves to `read`, which is exempt — the guard returns `allowed=True` with zero param scanning. The dangerous tool gets the identity of a safe one and skips all inspection.

The existing test `test_profile_alias_maps_exec_to_read_exempt` (`tests/adversarial/guard/test_tool_smuggling.py:39`) confirms the alias *resolves* but does not assert that the guard *blocks* the call. This is the gap.

## Prior Art

Drawbridge's TypeScript implementation does not have alias-to-exempt validation either (`clawmoat-drawbridge-sanitizer/src/` — grep returned no alias+exempt cross-check). This is net-new defense for Petasos.

Broader context: alias/identity smuggling is a known attack pattern in AI agent security. The MS-Agent framework disclosed a similar bypass where regex-based allowlists could be evaded through input transformation. OWASP's ASI02 category explicitly covers tool-name policy evasion.

## Remediation

### Approach: Reject alias targets that land in the exempt list

At alias-map construction time (both `_parse_profile` and `_merge_with_base` in `petasos/premium/profiles/__init__.py`, plus `_normalize_tool_name` in `guard.py`), validate that no alias target resolves to an exempt key.

### Changes

**1. `petasos/premium/profiles/__init__.py` — validation at construction**

In `_parse_profile()` (~L73–87) and `_merge_with_base()` (~L146–164), after building the final `alias_map` and `tool_exempt_list`, add:

```python
# Forbid aliasing onto exempt keys (GUARD-03)
alias_targets_in_exempt = set(alias_map.values()) & exempt_set
if alias_targets_in_exempt:
    raise ValueError(
        f"tool_alias_map targets cannot be exempt keys: {sorted(alias_targets_in_exempt)}"
    )
```

This catches the problem at profile creation/merge — fail loud, fail early.

**2. `petasos/premium/guard.py` — runtime defense-in-depth**

In `_normalize_tool_name()` (~L160–165), after resolving the combined alias, add a runtime check:

```python
resolved = combined.get(name, name)
# GUARD-03: alias must not land on exempt key
if (
    resolved != name
    and self._profile
    and resolved in self._profile.tool_exempt_list
):
    _logger.warning(
        "alias %r → %r blocked: target is exempt (GUARD-03)",
        name,
        resolved,
    )
    return name  # fall back to un-aliased name
```

This is defense-in-depth: even if a profile bypasses construction validation (e.g., direct `ResolvedProfile()` construction), the guard still refuses the redirect at runtime.

**3. `DEFAULT_TOOL_ALIASES` — structural invariant**

Assert at module load that no default alias target appears in any built-in profile's exempt list. This is a static guarantee; a one-line `assert` in `guard.py` after the constant definition is sufficient.

### Tests Required

| Test | File | Asserts |
|------|------|---------|
| `test_alias_onto_exempt_raises_at_parse` | `tests/unit/premium/test_profiles.py` | `_parse_profile` raises `ValueError` when alias target ∈ exempt list |
| `test_alias_onto_exempt_raises_at_merge` | `tests/unit/premium/test_profiles.py` | `_merge_with_base` raises `ValueError` for same condition |
| `test_alias_onto_exempt_runtime_fallback` | `tests/adversarial/guard/test_tool_smuggling.py` | Guard returns un-aliased name when alias → exempt (defense-in-depth) |
| `test_alias_exec_to_read_exempt_blocked` | `tests/adversarial/guard/test_tool_smuggling.py` | Full `evaluate()` call with exec→read+exempt profile returns `allowed=False` or scans params (not exempt bypass) |
| `test_default_aliases_not_in_builtin_exempt` | `tests/unit/premium/test_guard.py` | Structural: no default alias target is in any built-in profile's exempt list |
| `test_valid_alias_still_works` | `tests/unit/premium/test_guard.py` | Non-exempt alias targets (e.g., `bash→exec`) still resolve normally |

### What the existing test needs

`test_profile_alias_maps_exec_to_read_exempt` currently asserts `normalize("exec") == "read"` — it proves the bug. After the fix, this test should be updated to assert `normalize("exec") == "exec"` (fallback to un-aliased) or that the profile construction raises `ValueError`.

## Decisions Carried Forward

- **Defense-in-depth, not either/or.** Both construction-time rejection *and* runtime fallback. Construction-time is the primary gate; runtime is the backstop for direct `ResolvedProfile()` callers.
- **Fail-back to un-aliased name, not empty string.** Returning `""` would trigger the "invalid tool name" branch (L91–98), which blocks the call entirely. That's too aggressive — the original tool name is valid, it's the *redirect* that's dangerous.
- **No transitive alias resolution.** The alias map is single-hop (`combined.get(name, name)`). We don't need to chase chains like `exec→shell→read`. If multi-hop aliases are added later, this check must be extended.
- **Validation error, not silent drop.** At construction time, misconfigured profiles should raise `ValueError` so operators see the problem immediately in logs.

## Done When

- [ ] `_parse_profile` raises `ValueError` for alias targets that are also in `tool_exempt_list`
- [ ] `_merge_with_base` raises `ValueError` for the same condition
- [ ] `_normalize_tool_name` falls back to un-aliased name at runtime for alias→exempt
- [ ] All 6 tests listed above pass
- [ ] Existing `test_profile_alias_maps_exec_to_read_exempt` updated to assert the fix
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of Scope

- Multi-hop / transitive alias resolution (not currently implemented; tracked separately if needed)
- Profile schema versioning (profiles don't have a version field today)
- Drawbridge backport (Drawbridge is uncoupled; its own ticket if needed)
- Alias validation against non-exempt dangerous-tool lists (would require a "dangerous tools" registry — future work)
