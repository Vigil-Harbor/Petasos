# PET-36 — GUARD-03: Forbid Aliasing onto Exempt Keys

**Ticket:** PET-36 ("[RT GUARD-03] Profile alias exec->read + exempt read") · Plane `3103cc78-4c3e-4078-b9d0-fb61ce9e9f76` · Urgent
**Finding:** GUARD-03 (`external_id`) · **Parent:** PET-14 · **Blocks:** PET-12 (release) · **OWASP:** ASI02 (tool-use manipulation)
**Brief:** `docs/specs/TODO/PET-36.brief.md` · **Grounded against:** repo HEAD `d0af5aa` (`guard.py`/`profiles/__init__.py`/`test_tool_smuggling.py` unchanged since they last landed in `d927f4b`)

---

## Goal

Close the GUARD-03 tool-smuggling bypass: a profile that sets `tool_alias_map: {"exec": "read"}` together with `tool_exempt_list: ["read"]` causes `ToolCallGuard` to resolve a dangerous tool (`exec`) onto an exempt safe identity (`read`), returning `allowed=True` with zero param scanning. The fix forbids any alias target from landing on an exempt key, enforced **defense-in-depth**: a fail-loud `ValueError` at profile construction (primary gate) plus a runtime fall-back-to-un-aliased-name in the guard (backstop for direct `ResolvedProfile()` construction). A structural test guarantees no built-in default alias ever collides with a built-in exempt list.

---

## Scope

### Files to change (source)
- `petasos/premium/profiles/__init__.py` — in `_parse_profile` (L63–87) and `_merge_with_base` (L90–165): tighten the existing alias-value loop to reject non-string values, and add the profile-own alias→exempt collision check (raises `ValueError` naming the profile).
- `petasos/premium/guard.py` — add the profile-own-alias→exempt runtime fallback in `_normalize_tool_name` (L155–168).

### Files to change (tests)
- `tests/adversarial/guard/test_tool_smuggling.py` — update the existing `test_profile_alias_maps_exec_to_read_exempt` (L39) to assert the fix; add 2 new tests (runtime fallback, full-`evaluate()` block with premium active).
- `tests/test_profiles.py` — add 2 new tests (parse-time + merge-time `ValueError`).
- `tests/test_guard.py` — add 3 new tests (structural built-in invariant, valid-alias-still-works, D8 legitimate default-alias-onto-exempt regression guard).

### Files to leave alone
- **Built-in profile JSONs** (`general/customer_service/code_generation/research/admin.json`) — all five ship empty `tool_exempt_list` and `tool_alias_map`; no change needed and the structural invariant already holds.
- **`DEFAULT_TOOL_ALIASES`** (`guard.py:21–34`) — targets are `{exec, read, write, browser}`; unchanged.
- No new test directories. The brief's `tests/unit/premium/*` paths do not exist (see Decision D5).

---

## Decisions

### D1 — Defense-in-depth: construction-time reject AND runtime fallback, enforcing the SAME invariant
The invariant both gates enforce: **a profile's own `tool_alias_map` may not target a tool that is in that profile's `tool_exempt_list`.** Construction-time `ValueError` is the primary gate (catches malicious/misconfigured profiles at creation/merge — fail loud, fail early). The runtime check in `_normalize_tool_name` is the backstop for callers who bypass construction by building a `ResolvedProfile()` directly. **Why same invariant matters:** an earlier draft had the runtime check resolve via the *combined* map (`DEFAULT_TOOL_ALIASES` + profile), which made it fire on built-in default aliases too — a different (broader) invariant than construction, which only ever sees profile data. That asymmetry both broke legitimate behavior (see D8) and violated D4's "operators see the problem at creation." Both gates now key strictly on the profile's own alias entries. **Why two gates:** `ResolvedProfile` is a public frozen dataclass the existing test corpus constructs directly (`test_tool_smuggling.py:41`, `test_guard.py:37`), so construction validation is not the only path to a profile object. **How honored:** both code paths land in this spec; neither is optional; both inspect profile-own aliases only.

### D8 — A default alias landing on an operator-exempted target stays legal (scope boundary)
The check fires **only** for aliases the profile itself introduces, never for `DEFAULT_TOOL_ALIASES`. **Why:** exempting a canonical tool (`exec`) and letting its built-in aliases (`bash`/`shell`/`terminal`) inherit that exemption is the *intended* design — the operator deliberately trusts `exec`, and `bash` genuinely *is* `exec` (identity normalization, not identity change). The existing tests `test_guard_with_profile_exempt` (exempt `exec`, call `bash`) and `test_exempt_tool_skips_scanning` (exempt `read`, call `file_read`) encode this as legitimate and must stay green. GUARD-03 is specifically a **profile-introduced** alias redirecting a tool onto a *different* exempt identity (`exec→read`, where `read` is not `exec`'s canonical form). **How honored:** construction intersects only profile/merged alias values (never `DEFAULT_TOOL_ALIASES`); the runtime check fires only when `name in self._profile.tool_alias_map` (the redirect is profile-introduced). A profile that exempts a default target without redefining the alias passes both gates unchanged.

**Boundary note (operator-facing):** an operator who *redeclares* a default identity alias in their own profile (`tool_alias_map={"bash":"exec"}`) while exempting the target (`exec`) is **rejected at construction** with a `ValueError` — even though the semantically-identical config that omits the redundant alias (relying on the built-in `bash→exec`) is legal. This is the intended profile-own boundary, not a regression; the fix is to drop the redundant redeclaration. Fails loud with the profile-named message, never silent.

### D2 — Fall back to the un-aliased name, not empty string (carried from brief)
At runtime, when an alias resolves onto an exempt key, `_normalize_tool_name` returns the **pre-alias** name (e.g., `exec`), not `""`. **Why:** returning `""` trips the "invalid tool name: empty after normalization" branch (`guard.py:91–98`) and blocks the call entirely — too aggressive. The original tool name is legitimate; only the *redirect* is dangerous. Falling back to `exec` means the call proceeds through the normal tier/param-scan path under its true identity. **How honored:** capture the pre-alias name before the alias lookup; on collision, restore it.

### D3 — Single-hop aliasing only; no transitive resolution (carried from brief)
The alias map is single-hop (`combined.get(name, name)`). The collision check inspects direct alias *targets* only — it does not chase `exec→shell→read` chains. **Why:** the code has no multi-hop resolution today. **How honored:** the check is `set(alias_targets) & exempt`; if multi-hop is ever added, this check must be revisited (noted in Out of scope).

### D4 — Construction-time misconfiguration raises `ValueError`, not silent drop (carried from brief)
A profile whose alias targets an exempt key is a configuration error surfaced immediately. **Why:** operators must see the problem in logs at profile creation, not discover a silently-neutered alias later. **How honored:** `raise ValueError(f"tool_alias_map targets cannot be exempt keys: {sorted(collisions)}")` in both construction functions.

### D5 — Tests land in the repo's flat layout, not the brief's `tests/unit/premium/` (drift correction)
The brief specifies `tests/unit/premium/test_profiles.py` and `tests/unit/premium/test_guard.py`. **Those directories do not exist.** The repo uses a flat `tests/` layout: `tests/test_profiles.py`, `tests/test_guard.py`, and the existing `tests/adversarial/guard/test_tool_smuggling.py`. **Why:** introducing a parallel `tests/unit/premium/` tree would fork the test convention for one ticket. **How honored:** the Test plan maps each brief-named test to its real flat-layout home; no new directories are created.

### D6 — Structural invariant enforced by test, not an import-time `assert` (deviation from brief, with rationale)
The brief suggests "a one-line `assert` in `guard.py` after the constant definition" to guarantee no default alias target appears in a built-in exempt list. **This spec enforces it as a test (`test_default_aliases_not_in_builtin_exempt`) instead.** **Why:** a module-load assert would have to instantiate `ProfileResolver()` (which does JSON file I/O over all five built-ins) at `guard.py` import time — an import-time coupling and a crash-on-import failure mode for what is really a CI concern. The test gives the identical guarantee without coupling import to profile I/O. The invariant holds today (all built-ins ship empty exempt/alias), so the test is green on landing and becomes a regression tripwire for future built-in edits. **How honored:** the assert is omitted; the test is required and listed in Done-when.

### D7 — Compare alias targets case-insensitively against the lowercased exempt set (correctness nuance)
`tool_exempt_list` is stored lowercased (`profiles/__init__.py:85,144`), and `_normalize_tool_name` lowercases the input name before alias lookup (`guard.py:157`). Alias *values*, however, are stored as-is. The collision check therefore compares `{str(v).lower() for v in alias_map.values()} & exempt_set`, and the runtime check compares `resolved.lower() in tool_exempt_list`. **Why:** without `.lower()`, a profile could evade the construction check with `{"exec": "Read"}` + exempt `["read"]`; normalizing both sides closes that and matches the existing lowercase-everything discipline. This is fail-safe (it may reject a config whose mixed-case runtime resolution wouldn't actually bypass — acceptable, since such a config is already confusing). **How honored:** both checks lowercase alias values before set-intersection.

---

## Design

### Change 1 — `_parse_profile` (`profiles/__init__.py:63–87`)
Today `tool_exempt_list` is built inline in the `ResolvedProfile(...)` return (L85) and `alias_map` is the raw dict from L73. Strengthen the existing value-validation loop to also reject non-string values (closes a latent runtime `AttributeError` — `_normalize_tool_name` calls `.strip()` on the resolved value), compute the lowercased exempt set into a local, then cross-check before returning:

```python
alias_map = data.get("tool_alias_map", {})
for _k, v in alias_map.items():
    if not isinstance(v, str) or not v:
        raise ValueError("tool_alias_map values must be non-empty strings")

exempt_set = frozenset(s.lower() for s in data.get("tool_exempt_list", []))

# GUARD-03: a profile alias may not target one of its own exempt keys
collisions = {v.lower() for v in alias_map.values()} & exempt_set
if collisions:
    raise ValueError(
        f"profile {data.get('name', '?')!r}: tool_alias_map targets "
        f"cannot be exempt keys: {sorted(collisions)}"
    )

return ResolvedProfile(
    ...,
    tool_exempt_list=exempt_set,
    tool_alias_map=MappingProxyType(alias_map),
)
```

`alias_map` is the profile's OWN map — `DEFAULT_TOOL_ALIASES` is never merged into profiles (it lives only in `guard.py`), so this check has exactly the profile-own scope D1/D8 require. The non-string guard replaces the existing `if not v` loop (L74–76).

### Change 2 — `_merge_with_base` (`profiles/__init__.py:90–165`)
The merged `exempt` (L139–144, already a lowercased frozenset) and `alias` (L146–154) locals already exist. Add the same non-string guard to the existing alias loop (L151–153), then insert the cross-check immediately before the `return ResolvedProfile(...)` at L156:

```python
# (in the existing alias-value loop, L151-153)
for _k, v in val.items():
    if not isinstance(v, str) or not v:
        raise ValueError("tool_alias_map values must be non-empty strings")

# (immediately before the return, L156)
collisions = {v.lower() for v in alias.values()} & exempt
if collisions:
    raise ValueError(
        f"profile 'custom': tool_alias_map targets cannot be exempt keys: "
        f"{sorted(collisions)}"
    )
```

`alias` is the merged profile map (base `general` ships empty, so in practice the override's own entries); `DEFAULT_TOOL_ALIASES` is not part of it. Profile-own scope holds (D8).

### Change 3 — `_normalize_tool_name` (`guard.py:155–168`)
Capture the pre-alias name; suppress the redirect **only when the alias is profile-introduced AND targets an exempt key** (D8), comparing against a lowercased exempt set (covers directly-constructed profiles whose exempt list isn't pre-lowercased):

```python
def _normalize_tool_name(self, tool_name: str) -> str:
    name = tool_name.lower()
    name = _NAMESPACE_PREFIX_RE.sub("", name)
    if self._profile and self._profile.tool_alias_map:
        combined = {**DEFAULT_TOOL_ALIASES, **self._profile.tool_alias_map}
    else:
        combined = dict(DEFAULT_TOOL_ALIASES)
    pre_alias = name
    resolved = combined.get(name, name)
    # GUARD-03: a PROFILE-INTRODUCED alias must not redirect onto an exempt key.
    # Default aliases (bash->exec) onto an operator-exempted target stay legal (D8).
    if (
        resolved != pre_alias
        and self._profile
        and name in self._profile.tool_alias_map
        and resolved.lower() in {e.lower() for e in self._profile.tool_exempt_list}
    ):
        _logger.warning(
            "profile alias %r -> %r blocked: target is exempt (GUARD-03)",
            pre_alias,
            resolved,
        )
        resolved = pre_alias
    name = resolved
    name = name.strip()
    return name
```

Net effect:
- **Exploit blocked** — `exec→read` (profile-introduced) + exempt `read`: `name="exec"` ∈ profile alias map, `resolved="read"`, `"read"` ∈ exempt → suppress → returns `"exec"`; Step 4 `"exec" not in {"read"}` → no short-circuit → param scan runs under true identity.
- **Legitimate preserved (D8)** — exempt `exec`, call `bash` (default alias, no profile entry): `"bash" not in self._profile.tool_alias_map` → condition false → `resolved="exec"` → Step 4 `"exec" in {"exec"}` → exempt short-circuit, as before. `test_guard_with_profile_exempt` / `test_exempt_tool_skips_scanning` stay green.

### Why both gates are needed (interaction)
- A profile built via `ProfileResolver.resolve(dict)` → `_merge_with_base` or via `_parse_profile` (built-ins) → **rejected at construction** (Change 1/2). The malicious profile never becomes a `ResolvedProfile`.
- A profile built by calling `ResolvedProfile(...)` directly (bypassing both functions) → not validated at construction, but **neutralized at runtime** (Change 3) when the guard normalizes the tool name.

---

## Test plan

All tests use the repo's flat layout (D5). New + updated tests:

| Test | File | Asserts |
|------|------|---------|
| `test_alias_onto_exempt_raises_at_parse` | `tests/test_profiles.py` | `_parse_profile({...,"tool_alias_map":{"exec":"read"},"tool_exempt_list":["read"]})` raises `ValueError`. *(imports `_parse_profile`)* |
| `test_alias_onto_exempt_raises_at_merge` | `tests/test_profiles.py` | `ProfileResolver().resolve({...})` (→ `_merge_with_base`) raises `ValueError` for the same alias→exempt condition. |
| `test_alias_onto_exempt_runtime_fallback` | `tests/adversarial/guard/test_tool_smuggling.py` | A `ResolvedProfile` built directly (bypassing construction) with `exec→read`+exempt `read`: `guard._normalize_tool_name("exec") == "exec"` (un-aliased fallback). |
| `test_alias_exec_to_read_exempt_blocked` | `tests/adversarial/guard/test_tool_smuggling.py` | **Premium must be active** for `evaluate()` to pass Step 0 — the test injects a valid test license or monkeypatches `pipeline.is_premium_active` → True. With a directly-built `exec→read`+exempt `read` profile, `evaluate("exec", {...}, sid)` does **not** short-circuit as exempt: assert `reason not in ("premium inactive", "tool exempt per profile")` AND params were inspected (i.e., the call reached Step 5+). |
| `test_default_alias_onto_exempt_still_allowed` | `tests/test_guard.py` | **D8 legitimate case / F-1 regression guard:** profile exempts a DEFAULT alias target (`tool_exempt_list={"exec"}`, empty own alias map); `normalize("bash") == "exec"` (default alias NOT suppressed). Mirrors `test_guard_with_profile_exempt`. |
| `test_default_aliases_not_in_builtin_exempt` | `tests/test_guard.py` | Structural tripwire: for every built-in profile, `{v.lower() for v in DEFAULT_TOOL_ALIASES.values()} & profile.tool_exempt_list == set()`. *(imports `DEFAULT_TOOL_ALIASES`, `ProfileResolver`)* |
| `test_valid_alias_still_works` | `tests/test_guard.py` | A benign profile alias to a non-exempt target (e.g. `bash→exec`, no exempt) still resolves: `normalize("bash") == "exec"`. |
| **(update)** `test_profile_alias_maps_exec_to_read_exempt` | `tests/adversarial/guard/test_tool_smuggling.py:39` | Builds `ResolvedProfile` **directly**, so only the runtime branch applies (construction `ValueError` is unreachable here). Change the assertion from `normalize("exec") == "read"` to `normalize("exec") == "exec"` (runtime fallback). The `ValueError` path is covered separately by the parse/merge tests. |

Regression guards: the bug class is "a **profile-introduced** alias giving a tool an exempt identity it shouldn't have." `test_alias_exec_to_read_exempt_blocked` is the end-to-end regression; `test_default_alias_onto_exempt_still_allowed` guards the legitimate D8 case (and the two pre-existing tests it mirrors — `test_guard_with_profile_exempt`, `test_exempt_tool_skips_scanning` — must remain green, confirming no regression); `test_default_aliases_not_in_builtin_exempt` guards future built-in edits.

Pre-existing tests that MUST stay green (no edit, verify in the full-suite run): `test_guard_with_profile_exempt` (`tests/test_premium_integration.py:369`) and `test_exempt_tool_skips_scanning` (`tests/test_guard.py:282`) — both exempt a default alias target and rely on the default alias resolving onto it; D8's profile-own scoping keeps them passing. Also `test_tool_alias_map_empty_value_raises` (`tests/test_profiles.py:241`) — it matches `ValueError(match="non-empty")`; the strengthened message **must retain the `non-empty` substring** ("tool_alias_map values must be non-empty strings").

## Test command

```
py -3.13 -m pytest tests/test_profiles.py tests/test_guard.py tests/adversarial/guard/test_tool_smuggling.py tests/test_premium_integration.py -v && py -3.13 -m pytest -q && py -3.13 -m ruff check . && py -3.13 -m ruff format --check . && py -3.13 -m mypy --strict .
```

Targeted files first for fast signal (including `test_premium_integration.py`, which holds the `test_guard_with_profile_exempt` regression guard), then the full suite for no-regression, then `ruff check` + `ruff format --check` + `mypy --strict` per the brief's Done-when. `py -3.13` is a deliberate interpreter pin: bare `python` on this Windows host resolves to 3.10, which fails `requires-python>=3.11`; the `py` launcher selects the 3.13 env that has the project deps. ML-extra-dependent tests self-skip when extras are absent — skips are not failures.

---

## Done when

- [ ] `_parse_profile` raises `ValueError` when an alias target is also in `tool_exempt_list`. *(brief Done-when 1)*
- [ ] `_merge_with_base` raises `ValueError` for the same condition. *(brief 2)*
- [ ] `_normalize_tool_name` falls back to the un-aliased name at runtime for a **profile-introduced** alias→exempt collision (default aliases onto an exempted target are not suppressed — D8). *(brief 3)*
- [ ] All 7 new tests pass (paths per Test plan, flat layout — 6 from the brief + `test_default_alias_onto_exempt_still_allowed` added as the D8/F-1 regression guard). *(brief 4)*
- [ ] Existing `test_profile_alias_maps_exec_to_read_exempt` updated to assert `normalize("exec") == "exec"`. *(brief 5)*
- [ ] Pre-existing `test_guard_with_profile_exempt` and `test_exempt_tool_skips_scanning` still pass unchanged (D8 no-regression). *(brief 7)*
- [ ] `py -3.13 -m ruff check .`, `py -3.13 -m ruff format --check .`, and `py -3.13 -m mypy --strict .` clean. *(brief 6)*
- [ ] Full `pytest` suite shows no regression. *(brief 7)*

---

## Out of scope

- **Multi-hop / transitive alias resolution** (not implemented today; if added, the collision check must chase chains — D3). *(brief)*
- **Profile schema versioning** (profiles have no version field). *(brief)*
- **Drawbridge backport** (Drawbridge is uncoupled; its own ticket if needed). *(brief)*
- **Alias validation against a non-exempt "dangerous tools" registry** (no such registry exists; future work). *(brief)*
- **Module-load `assert`** for the structural invariant — deliberately replaced by a test (D6).

## Deferred (P2+)

- **Step 4's exempt check (`guard.py:114`) stays case-sensitive for directly-constructed profiles** (conventions/correctness R1). For profiles built via `_parse_profile`/`_merge_with_base` the exempt list is lowercased, so Step 4 is correct. A directly-built `ResolvedProfile` with a mixed-case `tool_exempt_list` could behave case-sensitively at Step 4 — but the GUARD-03 runtime check (Change 3) now lowercases both sides, so the *smuggle* path is closed regardless; only benign exempt-matching of an unusual mixed-case direct profile is affected. Pre-existing, not introduced here; normalizing Step 4 is out of GUARD-03 scope.
- **Test-command interpreter form `py -3.13`** (conventions R1 P2): sibling specs pin via absolute path / bare `python`. Kept deliberately — bare `python` is 3.10 on this host (fails `requires-python`), and `py -3.13` is a portable launcher pin. Cross-spec convention alignment, if desired, is a separate concern.
