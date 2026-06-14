# Edge-Cases Review — round 2

## Closure of round 1 findings
All round-1 edge-cases findings CLOSED: F-1 (TTL bounds same-tick miss), F-2 (503 + frontend revert — but see new F-1 below for the render-race re-entry), F-3 (Tier-3 tripwire), F-4 (bool-strict 422), F-5 (comment loss accepted/Deferred), F-6 (mount-only fetch — see new F-2 on reset scope), F-7 (gate at top covers init window), F-8 (`_reset_armed_cache`), F-9 (missing-parent-dir). Cross-lens correctness F-1/F-2 and conventions F-1/F-2/F-3 also verified CLOSED.

## Findings

### F-1 (P1): persist-failure (503) revert paints a detached DOM node — live banner can stay on the optimistic state
§ Frontend 3–4; against `petasos.js:578-579,366-368,398-406`. A `scan_result` SSE frame or 10 s poll firing **while a POST /armed is in flight** re-runs `renderDashboard`, which does `container.innerHTML = ""` (`:579`) — destroying the banner and its `paintBanner` closure, rebuilding from `Pet.state.armed` (the optimistic `next`). The in-flight `.then` revert closes over the **stale** `paintBanner`/detached nodes: it resets `Pet.state.armed` correctly but repaints a dead node; the visible (rebuilt) banner stays on the optimistic value. Net: a persist failure coinciding with a re-render shows EQUIPPED while file/gateway stay UNEQUIPPED — the round-1 F-2 fail-open re-entering via the render race. `_armedBusy` doesn't help (it gates clicks, not renders). Fix: revert by re-rendering from state — `Pet.state.armed = !next; if (Pet.state.tab === "obs" && _container) Pet.renderDashboard(_container);` (the established idiom at `:368,403,672`) — or have `paintBanner` re-query the live node from `_container` each call rather than close over it. Reconcile the success path to the authoritative `d.armed` too.

### F-2 (P2, Pre-ship recommended: yes): `_armedSeeded` not reset on switchTab → stale display on obs re-entry within a mount
§ Frontend 4. The spec mirrors `_historySeeded` (reset only in mount/unmount, never switchTab). But scan-history self-heals via SSE frames; armed-state has **no** SSE reconciliation (multi-tab sync is Deferred). So obs→cfg→obs within one mount reads cached `Pet.state.armed` and never re-fetches — banner shows a stale state for the mount lifetime if the bit changed out-of-band (the multi-writer scenario). Degrades gracefully (gateway enforces file truth; only display stale) → P2. Fix: reset `_armedSeeded = false` when `switchTab` enters obs (one cheap GET per tab switch), OR document that "on load" = "on mount" and accept stale display until multi-tab sync lands.

### F-3 (P3): writer-process cache TTL refresh can mask a same-size competing rewrite for up to 1 s
§ write_armed / Decision 2. `write_armed` refreshes `_ARMED_CACHE` with a fresh monotonic ts; a competing external same-size rewrite within the TTL window is masked on the dashboard's own read for ≤1 s. Bounded, self-corrects, matches accepted last-writer-wins. Fix: one sentence in Decision 2 acknowledging the writer-side mask is identical in shape to the gateway bound and equally accepted. No code change.

### F-4 (P3): tripwire rate-limit global not concurrency-guarded → burst + test flake
§ reference_plugin step 2. `_log_disarmed_bypass` does a lockless read-modify-write of `_last_disarm_log`; concurrent disarmed tool calls can both log (benign over-logging). The "logs once" test can flake under any concurrency. Fix: guard `_last_disarm_log` with a `threading.Lock` (matches `_ARMED_LOCK` discipline) OR weaken the test to "≥1 and not once-per-call" driven single-threaded. Over-logging is the safe failure direction.

### F-5 (P4): fail-secure read shows EQUIPPED during a mid-swap read — cosmetic display flap, no enforcement risk
§ read_armed / Decision 5. Working as designed (gateway independently fails secure → enforce). Noted for completeness; no action.

## Summary
P0: 0 | P1: 1 | P2: 1 | P3: 2 | P4: 1

STATUS: RED P0=0 P1=1 P2=1 P3=2 P4=1
