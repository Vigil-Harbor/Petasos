# Conventions Review — round 2

## Closure of round 1 findings
All round-1 conventions findings CLOSED: F-1 (split into new `_armed.py`, `_paths` stays pure), F-2 (`_post_tool_call` rationale corrected), F-3 (`_reset_armed_cache` + autouse fixture in `tests/test_console_armed.py`), F-4/F-5/F-6/F-7 (deferral precedent, N=2 allowlist, atomic-write idiom, FE posture). Cross-lens correctness F-1/F-2 and edge F-1/F-2/F-7 also verified CLOSED. New `tests/test_console_armed.py` follows the `test_console_*` one-area-per-module convention (siblings: handlers/playground/validation).

## Findings

### F-1 (P3): make the Tier-3 reconciliation explicit by citing the prior decisions
§ Decision 1. The recorded floor invariant (PET-23 CFG-04 mutable-binding, PET-75 #1 safety-nets, PET-107 D4) prohibits a *config value / in-process rebind / feature toggle* from lowering Tier-3. Decision 1's master switch is none of these — it gates the whole plugin above `_guard.evaluate`, leaving the floor mechanism intact (re-arm snaps back; tombstone persists). The framing is consistent, but Decision 1 doesn't name the prior decisions it reconciles against. Fix: add a clause citing PET-23/PET-75/PET-107 and stating the master switch is a new axis those decisions did not contemplate, not a contradiction — pre-writes the eventual decision-page rationale.

### F-2 (P3): note that `write_armed`'s function-local imports match `_persist_config`'s cold-path idiom
§ `_armed.py`. `read_armed` (hot path) imports nothing locally; `write_armed` (cold path) imports yaml/tempfile/contextlib function-locally. This is correct (keeps yaml out of the gateway's per-call `read_armed` import, mirrors `server.py:_persist_config:51-54`) but unstated. Fix: one-line note in the `_armed.py` Notes block.

### F-3 (P4): drop the `import time as _time` alias
§ reference_plugin step 2. Use a module-top `import time` + `time.monotonic()` (verify `time` isn't already imported by the PET-107 lineage/spawn-budget code; reuse if so). Pure nit.

## Silent-additions check
All seven Decisions classify as (a) brief-authorized or (c) spec-level additions with rationale (mount-only fetch, disarm tripwire, 503 contract — all originate from round-1 findings, all carry rationale). No (d) silent scope/behavior additions. Scope deferrals (BUG-B, multi-tab SSE) shrink scope deliberately, matching the brief.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 2 | P4: 1

STATUS: GREEN
