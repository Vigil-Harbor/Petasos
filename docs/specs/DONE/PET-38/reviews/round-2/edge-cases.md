# Edge-Cases Review -- round 2

## Closure of round 1 findings
All R1 findings CLOSED. Key fixes: `_MAX_PARAM_TEXT_LEN` rename, truncation documented as non-JSON, `evaluate()` catch-all deferred in Out of Scope, `mypy --strict` added.

## Findings

### F-1: Double truncation with inconsistent limits (P3)
Two truncation layers (`safe_json_dumps` per-value, `_MAX_PARAM_TEXT_LEN` aggregate) operate independently with same 1M limit. Narrow overlap where per-value marker is itself truncated. Harmless — scanner doesn't interpret markers semantically.

### F-2: `set`/`frozenset` falls through to `_default` (P3)
Non-JSON-native iterables get `"[Unserializable: set]"` via `_default`. Safe behavior; MCP tool schemas don't emit sets.

### F-3: Non-string dict keys fall through to catch-all (P2)
Dict with non-string keys (e.g., `{(1,2): "v"}`) causes `json.dumps` TypeError, caught by outer catch-all. Entire value becomes `"[Unserializable]"`. MCP tool params always have string keys; catch-all protects.

### F-4: `id()` reuse — theoretical only (P4, retracted to informational)
`seen` set only contains IDs of live objects on the call stack. `discard` on scope exit prevents false positives. Pattern is sound.

### F-5: `CancelledError` / `KeyboardInterrupt` — correctly not caught (retracted)
`except Exception` is the right asyncio-safe pattern in Python 3.11+.

### F-6: All-None params — existing test covers (P3, informational)

### F-7: No adversarial guard test for DAG case (P3)
Unit test #7 covers `safe_json_dumps` directly. Guard-level DAG test not needed — not an attack vector.

### F-8: `__init__.py` re-exports (P4)
Leading underscore convention is sufficient. No `__init__.py` change needed.

### F-9: `max_depth=-1` edge (P4)
Not reachable; hardcoded at 32.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 4 | P4: 2

STATUS: GREEN
