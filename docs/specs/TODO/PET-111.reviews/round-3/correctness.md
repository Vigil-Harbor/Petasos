# Correctness Review — round 3

## Closure of round 2 findings
correctness/F-1 (P2, tripwire reset seam) CLOSED (`_reset_disarm_log()` + lock + autouse fixture + weakened test). edge/F-1 (P1, detached node) CLOSED (live re-query + reconcile to d.armed). edge/F-2,F-3,F-4 and conventions/F-1,F-2 CLOSED. conventions/F-3 (P4, `_time` alias) REOPENED as P1 — see below.

## Findings

### F-1 (P1): spec instructs reuse of a non-existent `import time` in the reference plugin
§ reference_plugin step 2 (spec:293-295), used at the tripwire `time.monotonic()` (spec:317). `docs/deployment/reference_plugin/__init__.py` imports only `asyncio, base64, logging, os, threading, uuid` (`:15-23`); full-file grep for `time` = zero matches; the PET-107 lineage/spawn-budget code uses no time source. Following "reuse it; do not add a `_time` alias" literally → no import added → `NameError` on the first disarmed tool call, on the kill-switch path the tripwire instruments. NEW defect introduced by the round-3 edit that closed conventions/F-3 (the round-2 finding had the correct hedge "verify … reuse if so"; the spec resolved it by asserting a false antecedent). Fix: "Add `import time` to the module-top block (`:17-22`) — not currently imported; do not add a `_time` alias." Drop the false PET-107 clause.

## Verified-correct (no new defect from the round-3 edits)
- Lock-guarded tripwire: clock read outside lock, compare-and-set inside `_disarm_log_lock` (`threading` already imported `:21`); `_reset_disarm_log()` → 0.0, `monotonic()` ≫ 0, first post-reset call always logs — correct seam.
- Frontend reconcile-to-`d.armed`: `ok` gate matches the `_req` envelope (`_status`/`error` at `:260,263,268,274`); 503 → revert; success → reconcile to `d.armed`; re-query + interleaved-render rebuild converge to file-truth on both axes.
- Anchor integrity: all cited anchors verified against current files; no drift (latest plugin-touching commit PET-107 `5ed09dd` reflected).
- BUG-A merge correct (`{**preserved, **export}`, allowlist = popped pair). Done-when 1:1 coverage holds. Ticket PET-111 (Todo) matches brief+spec.

## Summary
P0: 0 | P1: 1 | P2: 0 | P3: 0 | P4: 0

STATUS: RED P0=0 P1=1 P2=0 P3=0 P4=0
