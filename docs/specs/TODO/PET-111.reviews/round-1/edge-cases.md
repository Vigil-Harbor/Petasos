# Edge-Cases Review — round 1

## Findings

### F-1 (P1): cache `(mtime_ns, size)` key can miss a same-size, same-tick toggle → disarm may never take effect
`enabled: true`↔`false` differs by ~1 byte and a full `safe_dump` rewrite can leave size effectively uninformative; the gateway (which never calls `write_armed`) re-parses only when ITS stat shows a changed key. If `os.replace` lands in the same observable mtime tick with unchanged size, the gateway serves the stale bool until the next unrelated config write — staleness bounded by "next mtime-changing write," not "next tool call." Fix: bound staleness with a short TTL (force re-stat+re-parse if cache older than ~1s) and/or a content fingerprint on the miss path. Add a test that flips true→false with identical serialized size (pad a sibling key) and asserts the reader observes it.

### F-2 (P1): persist failure returns 200+warning; frontend reverts only on error/4xx → UI/enforcement divergence (arm = silent fail-open)
Windows file lock (Defender/UI model switcher, footgun #11) → `write_armed` returns False → `set_armed` returns HTTP 200 + `warning`. Frontend optimistic toggle reverts only on `error||_status>=400`, so it shows the requested state while the file is unchanged and the gateway keeps the old state. For ARM (false→true) that fails to persist: UI says EQUIPPED, enforcement stays OFF — silent fail-open of the master control. Fix: return non-200 (409/503) from POST /armed when `write_armed` is False so the revert path fires uniformly; frontend must revert / mark "NOT APPLIED — still <prior>" on warning too. Test the persist-failure response shape; spec the arm-direction case.

### F-3 (P2): disarm bypasses the Tier-3 floor for terminated sessions with no tripwire
Gate sits above `_guard.evaluate`, so a Tier-3-terminated (presumed-compromised) session passes all tool calls through while disarmed, then snaps back on re-arm. This overrides the "Tier 3 cannot be disabled" invariant for the disarmed interval. Acknowledge in Decision 1/5 that Unequipped overrides even the Tier-3 floor (intended, operator-initiated) AND emit a rate-limited WARNING tripwire at the disarm gate (`PETASOS_DISARMED tool=... — enforcement bypassed by operator`) so a terminated session executing tools is attributable.

### F-4 (P2, Pre-ship recommended: yes): POST /armed validation contract under-specified
Handle `{}` (missing armed), `{"armed": null}`, `{"armed": 1}`, `{"armed": "true"}`, non-dict. `isinstance(True, int)` is True, so guard with `isinstance(body["armed"], bool)` (bool-first). Pin: 422 `{"field":"armed","message":"Must be a boolean"}` when `"armed" not in body or not isinstance(body["armed"], bool)`. Test the rejected inputs on BOTH surfaces.

### F-5 (P3): write_armed strips YAML comments on every toggle
`safe_load`→`safe_dump` round-trip drops comments/normalizes formatting (same class as BUG-A, opposite direction); toggles write far more often than a Config Editor save. Matches existing `_persist_config` behavior — acknowledge as accepted in a Note + the model-switcher write race in Risks. No code change required round 1.

### F-6 (P2): per-render getArmed refetch causes flicker, request spam, and an optimistic-toggle race
`renderDashboard` runs on EVERY `scan_result` SSE frame (`petasos.js:366-368`) and every 10s poll (`:398-406`), not just mount. "Fetch on each obs render" → a GET /armed per scan event, and a mid-flight frame can repaint the banner to the stale file value, visibly bouncing the operator's click. Fix: fetch armed only on actual mount/focus (guard like `_historySeeded`), and suppress refetch while a POST is in flight (`_armedBusy`).

### F-7 (P2): disarmed boot still scans via fallback during the init window
The `_is_armed()` gate is only on the *initialized* branch; the init-in-progress branch returns `_fallback_pre_tool_call` unconditionally, which can BLOCK a disarmed-booted session during cold start — contradicts "Unequipped = zero enforcement." Fix: put `if not _is_armed(): return None` at the very TOP of `_pre_tool_call` (before `_ensure_initialized()`), covering init-in-progress, init-failed, and initialized uniformly. (Also resolves correctness F-1.) Test: enabled:false boot + in-progress + injection payload → None.

### F-8 (P3): read cache has no reset seam → test isolation + coincidental-key staleness
Module-global `_ARMED_CACHE` persists across tests (distinct tmp files may collide on `(mtime_ns,size)`). Add `_reset_armed_cache()` (set None under lock) for autouse test reset; pair with F-1 TTL to bound the production coincidental-key case.

### F-9 (P3): missing-parent-dir write path untested
`mkstemp(dir=res.path.parent)` raises FileNotFoundError when the parent dir is absent (fresh install / orphaned profile, footgun #15) — caught → False (fail-safe) but combined with F-2 the UI diverges. Add a missing-parent-dir case to the write_armed fail-path test; decide explicitly NOT to mkdir.

## Summary
P0: 0 | P1: 2 | P2: 4 | P3: 3 | P4: 0

STATUS: RED P0=0 P1=2 P2=4 P3=3 P4=0
