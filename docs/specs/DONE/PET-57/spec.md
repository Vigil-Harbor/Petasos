# PET-57 — PROF-02: Retained Dict Ref Bypasses MappingProxyType Immutability

**Ticket:** PET-57 · **Finding:** PROF-02 · **Priority:** Medium
**OWASP:** ASI07 — Insufficient threat-detection coverage
**Parent:** PET-14 · **Blocks:** PET-12 (release)

---

## Goal

Prevent caller-retained dict references from mutating `ResolvedProfile` fields after construction. `_parse_profile` wraps caller-supplied dicts with `MappingProxyType` but does not copy the underlying dict first — the proxy is a read-only *view*, not an independent copy. A caller that retains a reference to the source dict can silently mutate the profile's `severity_overrides` map, bypassing severity-floor guards (PIPE-07 vector) and violating the frozen-export invariant. This change adds defensive `dict()` copies before proxy wrapping.

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/premium/profiles/__init__.py` | Add `dict()` copy around `data.get("severity_overrides", {})` at L113 and around `alias_map` at L118 in `_parse_profile` |

### New files

| File | Purpose |
|------|---------|
| `tests/test_profiles_retained_ref.py` | 3 regression tests proving defensive copy breaks the retained-reference link |

### Files unchanged

- `petasos/premium/profiles/_merge_with_base` (L122–204) — already constructs fresh dicts via `dict(base.severity_overrides)` (L133) and `dict(base.tool_alias_map)` (L178) before wrapping. No change needed.
- `petasos/premium/profiles/_load_builtins` (L212–218) — `json.loads` produces ephemeral dicts with no external reference. Not vulnerable.
- `petasos/scanners/minimal.py` — unrelated to this fix.
- `petasos/pipeline.py` — no pipeline changes.
- `petasos/config.py` — no config changes.

## Decisions

### Decision 1: Shallow copy is sufficient

Both `severity_overrides` and `tool_alias_map` are `dict[str, str]` — all values are immutable strings. A shallow `dict()` copy fully breaks the reference link. Deep copy or recursive freezing is unnecessary overhead. This follows the same `MappingProxyType(dict(...))` pattern already used in `PetasosConfig.__post_init__` for `frequency_weights` (`config.py:193`).

### Decision 2: `_merge_with_base` is already safe — no change

`_merge_with_base` constructs fresh dicts via `dict(base.severity_overrides)` (L133) and `dict(base.tool_alias_map)` (L178) before proxy-wrapping. The caller's override dict values are merged into these fresh copies, not wrapped directly. No retained-reference vector exists on the merge path.

### Decision 3: Built-in profiles are not affected — no change

`_load_builtins` feeds `json.loads` output to `_parse_profile`. `json.loads` produces a fresh dict on every call with no external references. The vulnerability requires a caller-retained reference, which doesn't exist for built-in profiles.

### Decision 4: `alias_map` copy is defense-in-depth

At L98, `alias_map` is already a fresh dict from the comprehension `{k: v.strip() for k, v in alias_map.items()}`. Wrapping it in `dict()` is technically redundant today, but makes the defensive intent explicit and guards against future refactors that might remove the comprehension (e.g., if the strip-and-validate logic is extracted elsewhere).

### Decision 5: Fix is defense-in-depth — the public API path is already safe

`ProfileResolver.resolve(dict)` dispatches to `_merge_with_base` (L228–230), which already constructs fresh dicts before proxy-wrapping (Decision 2). The only production call-site for `_parse_profile` is `_load_builtins`, which uses `json.loads` output with no external references (Decision 3). The vulnerability in `_parse_profile` is exploitable only by direct callers of the private function — test code (already imports it) and downstream integrators who bypass `ProfileResolver`. The fix is still warranted as defense-in-depth: `_parse_profile` is importable (no `__all__`, underscore prefix is convention only), and future code paths may call it with externally-supplied data.

## Design

### 1. Defensive copy in `_parse_profile` — `severity_overrides` (L113)

Current:
```python
severity_overrides=MappingProxyType(data.get("severity_overrides", {})),
```

After:
```python
severity_overrides=MappingProxyType(dict(data.get("severity_overrides", {}))),
```

### 2. Defensive copy in `_parse_profile` — `tool_alias_map` (L118)

Current:
```python
tool_alias_map=MappingProxyType(alias_map),
```

After:
```python
tool_alias_map=MappingProxyType(dict(alias_map)),
```

These are the only two `MappingProxyType` calls in `_parse_profile`. Both now wrap a fresh `dict()` copy, breaking the reference link to any caller-held object.

## Test plan

### Regression tests — `tests/test_profiles_retained_ref.py`

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_severity_overrides_not_mutated_by_caller` | Construct profile via `_parse_profile(data)`, then mutate `data["severity_overrides"]` — profile's `severity_overrides` must be unchanged |
| 2 | `test_tool_alias_map_not_mutated_by_caller` | Construct profile via `_parse_profile(data)`, then mutate `data["tool_alias_map"]` — profile's `tool_alias_map` must be unchanged. Note: the L98 comprehension already breaks this link today; test validates the invariant end-to-end and guards against future removal of the comprehension (per Decision 4) |
| 3 | `test_empty_overrides_not_shared` | Construct two profiles from data dicts with no `severity_overrides` key — verify the resulting `severity_overrides` objects are not the same object. Invariant check: `data.get(key, {})` evaluates `{}` freshly per call, so this validates the no-shared-state property rather than regression-testing the `dict()` wrapping specifically |

### Existing test verification

| File | Impact |
|------|--------|
| `tests/test_profiles.py` | No changes — existing tests exercise `_parse_profile` and `_merge_with_base` but do not test post-construction mutation. All must remain green. |

## Test command

```
python -m pytest tests/test_profiles_retained_ref.py tests/test_profiles.py -v && ruff check . && ruff format --check . && mypy --strict petasos/premium/profiles/__init__.py
```

## Done when

- [ ] `_parse_profile` wraps `dict(...)` around `data.get("severity_overrides", {})` before `MappingProxyType`
- [ ] `_parse_profile` wraps `dict(alias_map)` before `MappingProxyType` for `tool_alias_map`
- [ ] `tests/test_profiles_retained_ref.py` exists and passes — all three cases (severity mutation, alias mutation, empty-dict isolation)
- [ ] `mypy --strict petasos/premium/profiles/__init__.py` passes
- [ ] Existing `test_profiles.py` suite still green
- [ ] `ruff check .` and `ruff format --check .` clean

## Out of scope

- Deep-copy or recursive freezing of profile dicts — unnecessary for `str->str` maps.
- Refactoring `MappingProxyType` to a custom frozen-dict class — overhead without benefit for current types.
- Fixing `_merge_with_base` — already safe; no change needed.
- Addressing CPython-level `MappingProxyType` bypass (ctypes / C-API) — out of Petasos's threat model.
- Adversarial end-to-end test through the pipeline — the fix is at the data-structure layer; the `_parse_profile` unit tests are the correct verification surface.

## Deferred (P2+)

- **Direct `ResolvedProfile` construction bypass (P3):** A caller can construct `ResolvedProfile(severity_overrides=MappingProxyType(attacker_dict), ...)` directly, bypassing `_parse_profile`. The same retained-reference vulnerability exists at this layer. A `__post_init__` defensive copy could address it in a follow-up ticket. P3 because direct-construction callers are already wrapping in `MappingProxyType` explicitly.
- **Test 2 diagnostic limitation (P2):** `test_tool_alias_map_not_mutated_by_caller` would pass even without the `dict(alias_map)` change because the L98 comprehension already creates a fresh dict. The test validates the end-to-end invariant and guards against future refactors removing the comprehension, but does not regression-test the specific `dict()` wrapping. Acknowledged; test retained as defense-in-depth.
- **Test 3 non-diagnostic for fix (P4):** `test_empty_overrides_not_shared` validates a no-shared-state invariant rather than regression-testing the `dict()` copy, because `data.get(key, {})` evaluates `{}` freshly per call. Retained as invariant documentation.
- **`mypy --strict` scope (P4):** Test command scopes mypy to `petasos/premium/profiles/__init__.py` rather than whole-project. CI runs `mypy --strict .` and catches transitive issues. Scoped approach is acceptable for local iteration speed.
