# PET-38 — GUARD-05: Circular/Deep Params Crash `_scan_params`

**Ticket:** PET-38 · **Finding:** GUARD-05 · **Priority:** Urgent
**Parent:** PET-14 · **Blocks:** PET-12 (release)

## Goal

Harden `ToolCallGuard._scan_params` against circular references, deeply nested structures, and oversized payloads in `tool_params`. The current code uses bare `json.dumps` (L223 of `guard.py`) which raises `RecursionError` on circular dicts — an unhandled crash that violates the pipeline's "never throws" invariant. Ship a `safe_json_dumps` utility that mirrors Drawbridge's `safeStringify` semantics, wire it into `_scan_params` with a size cap, and add a catch-all to enforce the never-throws contract.

## Scope

### Files to create

| File | Purpose |
|------|---------|
| `petasos/premium/_safe_json.py` | `safe_json_dumps()` — circular-safe, depth-limited, size-capped JSON stringification |
| `tests/test_safe_json.py` | Unit tests for `safe_json_dumps` |

### Files to modify

| File | Change |
|------|--------|
| `petasos/premium/guard.py` | Replace `json.dumps` with `safe_json_dumps` in `_scan_params`; add size cap on assembled param text; add catch-all try/except; remove unused `import json` |
| `tests/adversarial/guard/test_tool_smuggling.py` | Add adversarial tests: circular dict, deep nesting, large params |
| `tests/test_guard.py` | Add `test_scan_params_exception_returns_unsafe` |

### Files to leave alone

- `petasos/config.py` — no new config fields; depth/size limits are hardcoded constants (not operator-tunable)
- `petasos/pipeline.py` — no changes
- `petasos/premium/alerting.py`, `petasos/premium/audit.py` — `_safe_json` is available for future use but not wired in this ticket

## Decisions

### D1: New utility file, not inline

`safe_json_dumps` is a general-purpose function usable by audit/alerting serialization paths in the future. A dedicated `_safe_json.py` module keeps it independently testable and importable. The leading underscore marks it as internal to the `petasos.premium` package.

### D2: `set[int]` for seen tracking, not `WeakSet`

Python dicts and lists are not weakly referenceable, so `WeakSet` is not viable. Using `id()` with a regular `set` and `discard` on scope exit is the standard Python pattern for circular-reference detection.

### D3: `((), True)` on catch-all, not `allowed=False`

The catch-all wraps `_scan_params`, not `evaluate`. Returning `((), True)` (no findings, `param_scan_unsafe=True`) lets the caller (`evaluate`) make the final allow/block decision based on tier context — consistent with the existing error-handling pattern at L235-240 where pipeline errors already return `((), True)`.

### D4: Hardcoded depth and size limits

Depth limit 32 and size cap 1 MB are safe defaults for tool parameter structures — legitimate params rarely exceed 5-10 nesting levels, and 1 MB exceeds any reasonable tool param payload. These happen to align with Drawbridge's `safeStringify` defaults but are chosen independently for Petasos's threat model. They are internal constants, not config-surface — operator tuning adds complexity without clear value for a safety cap.

## Design

### 1. `petasos/premium/_safe_json.py`

Single public function: `safe_json_dumps(value, *, max_depth=32, max_size=1_000_000) -> str`.

Behavior:
- **Walk** the value tree recursively, tracking visited container `id()`s in a `set[int]`.
- Circular reference (same `id()` re-entered) → replace with `"[Circular]"`.
- Depth exceeded (`depth > max_depth`) → replace with `"[Depth limit]"`.
- After walking, call `json.dumps(sanitized, default=_default)` where `_default` returns `f"[Unserializable: {type(obj).__name__}]"` for non-JSON-native types.
- Outer `try/except Exception` → return `'"[Unserializable]"'` (valid JSON string) for any remaining edge case.
- If `len(text) > max_size` → truncate and append `"...[truncated]"`. Note: truncated output is intentionally not valid JSON — it is consumed as plaintext by the scanner, not parsed.

The `seen` set uses `discard` in a `finally` block to support DAG-shaped data (same node reachable via multiple paths — not circular, just shared). Only re-entry of a node *currently on the stack* is circular.

### 2. `petasos/premium/guard.py` changes

**2a. Import swap.** Remove `import json` (L3). Add `from petasos.premium._safe_json import safe_json_dumps`.

**2b. Replace serialization in `_scan_params` (L215-225).** The current loop:
```python
for value in tool_params.values():
    if value is None:
        continue
    if isinstance(value, str):
        parts.append(value)
    else:
        try:
            parts.append(json.dumps(value))
        except TypeError:
            parts.append(str(value))
```

Becomes:
```python
for value in tool_params.values():
    if value is None:
        continue
    if isinstance(value, str):
        parts.append(value)
    else:
        parts.append(safe_json_dumps(value))
```

The `try/except TypeError` is removed — `safe_json_dumps` handles all failure modes internally (TypeError via `_default`, RecursionError via the walk, anything else via the outer catch-all).

**2c. Size cap on assembled param text.** Add a module-level constant (alongside existing `_NAMESPACE_PREFIX_RE` and `_PREMIUM_INACTIVE`):

```python
_MAX_PARAM_TEXT_LEN = 1_000_000  # 1M characters
```

After `param_text = "\n".join(parts)` (L227), add:

```python
if len(param_text) > _MAX_PARAM_TEXT_LEN:
    _logger.warning(
        "param text exceeds length cap (%d > %d chars), truncating; session=%s",
        len(param_text), _MAX_PARAM_TEXT_LEN, session_id,
    )
    param_text = param_text[:_MAX_PARAM_TEXT_LEN]
```

This prevents DoS via large (but non-circular) param payloads that would cause expensive pipeline scanning. The per-value `max_size` in `safe_json_dumps` caps individual values; this caps the aggregate.

**2d. Catch-all around `_scan_params` body.** Wrap the entire method body in `try/except Exception` (existing signature and type annotations preserved):

```python
async def _scan_params(
    self,
    tool_params: dict[str, Any],
    session_id: str,
) -> tuple[tuple[ScanFinding, ...], bool]:
    try:
        # ... all existing logic ...
    except Exception:
        _logger.exception("_scan_params failed unexpectedly, marking unsafe")
        return (), True
```

This enforces the never-throws contract for the param-scanning path. Note: `evaluate()` itself does not get a catch-all in this ticket — that is a broader hardening task deferred to a future ticket. The `_logger.exception` call ensures the error is observable in logs.

### 3. Interaction with existing code

- **`str(value)` fallback removed.** The old `except TypeError: parts.append(str(value))` was a fallback for non-serializable types. `safe_json_dumps` handles this with `_default`, producing `"[Unserializable: ClassName]"` inside valid JSON — more informative and consistently formatted than bare `str()`.
- **Pipeline scan of truncated text.** Truncation at 1 MB means the scanner sees a prefix. This is acceptable — the purpose is detecting injection patterns, and 1 MB of text is more than sufficient for pattern matching. Content beyond the cap is not security-relevant for the guard's purpose.
- **No config changes.** The 32-depth and 1M-char limits are safety caps, not tuning knobs. Adding them to `PetasosConfig` would imply they're operator-adjustable, which creates a footgun (setting depth to 1000 re-enables the DoS).

## Test plan

### `tests/test_safe_json.py` — unit tests for `safe_json_dumps`

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_normal_dict` | Normal dict → standard JSON output, no placeholders |
| 2 | `test_circular_dict` | `d = {}; d["self"] = d` → JSON string containing `"[Circular]"` |
| 3 | `test_circular_list` | `a = []; a.append(a)` → JSON string containing `"[Circular]"` |
| 4 | `test_depth_limit` | 50-level nested dict with `max_depth=10` → string containing `"[Depth limit]"` |
| 5 | `test_unserializable_type` | Object with no JSON repr → string containing `"[Unserializable"` |
| 6 | `test_size_cap` | 2 MB value → truncated output ending with `"...[truncated]"` |
| 7 | `test_dag_shared_node_not_circular` | Same dict reachable via two paths → no `"[Circular]"` (DAG, not cycle) |
| 8 | `test_mixed_types` | Dict with nested lists, ints, bools, None → valid JSON |
| 9 | `test_never_throws` | Pathological input (object whose `__iter__` raises) → returns a string, does not raise |

### `tests/adversarial/guard/test_tool_smuggling.py` — adversarial guard tests

| # | Test | Asserts |
|---|------|---------|
| 10 | `test_circular_dict_no_crash` | `evaluate()` with circular dict param returns `GuardResult` without raising |
| 11 | `test_deeply_nested_dict_no_crash` | 500-level nested dict param does not raise `RecursionError` |
| 12 | `test_large_params_truncated` | 2 MB string param is scanned without timeout/OOM; result is valid |

### `tests/test_guard.py` — catch-all test (append to existing file)

| # | Test | Asserts |
|---|------|---------|
| 13 | `test_scan_params_exception_returns_unsafe` | Mock `Pipeline.inspect` to raise `RuntimeError` → `_scan_params` returns `((), True)` without propagating |

## Test command

```
python -m pytest tests/test_safe_json.py tests/adversarial/guard/test_tool_smuggling.py tests/test_guard.py -v && ruff check . && ruff format --check . && mypy --strict .
```

## Done when

- [ ] `petasos/premium/_safe_json.py` exists with `safe_json_dumps` function
- [ ] `_scan_params` uses `safe_json_dumps` instead of `json.dumps`
- [ ] `_scan_params` has catch-all returning `((), True)` on any exception
- [ ] Total param text size capped at 1 MB with truncation + warning log
- [ ] All tests in the test command pass (13 new + existing)
- [ ] `ruff check .`, `ruff format --check .`, and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of scope

- Streaming param scanning for very large payloads (would require pipeline changes)
- Drawbridge backport (`safeStringify` already exists there)
- Schema validation of tool params against MCP tool definitions (separate feature, not a guard concern)
- Rate limiting on `_scan_params` calls (handled at the frequency tracker level)
- Making depth/size limits configurable via `PetasosConfig` (safety caps, not tuning knobs)
- Wiring `safe_json_dumps` into audit/alerting paths (future ticket if needed)
- Catch-all on `evaluate()` itself (broader hardening beyond `_scan_params` — separate ticket)
