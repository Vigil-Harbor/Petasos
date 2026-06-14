# Edge-Cases Review — round 3

## Closure of round 2 findings
All round-2 findings CLOSED in shape: F-1 (paintBanner re-query + reconcile to authoritative d.armed), F-2 (`_armedSeeded` reset on switchTab→obs), F-3 (writer-cache mask note in Decision 2), F-4 (tripwire lock). Cross-lens correctness F-1 (reset seam) CLOSED. BUT the F-4 lock closure depends on a `time` import that does not exist — see F-1 below.

## Findings

### F-1 (P1): `import time` does not exist in the reference plugin — disarm tripwire raises NameError, breaking never-throw on the disarm path
§ reference_plugin step 2 instructs "Use the module-top `import time` (PET-107 already imports it — reuse it; do not add a `_time` alias)." Verified FALSE: `reference_plugin/__init__.py:15-23` imports only `asyncio, base64, logging, os, threading, uuid`; grep for `time` = zero matches; PET-107 lineage/spawn-budget code uses no time source. Followed literally, the implementer adds no import and the first disarmed `_pre_tool_call` → `_log_disarmed_bypass` → `time.monotonic()` raises `NameError`, propagating out of `_pre_tool_call` (the gate calls `_log_disarmed_bypass` directly, NOT inside the `_is_armed` try/except) — violating "Pipeline never throws" on exactly the kill-switch path. (`server.py:104` imports `time` — likely the source of the false claim; different module.) Fix: instruct to ADD `import time` to the module-top block; drop the false "reuse" clause. Add a wiring-test never-throw assertion (disarmed `_pre_tool_call` returns None without raising).

### F-2 (P2, Pre-ship recommended: yes): `paintBanner()` derefs `_container` which is null after unmount → in-flight promise tail throws
§ Frontend 3 specifies `_container.querySelector(".equip-banner")`. After `Pet.unmount` (`:1177` sets `_container = null`), an in-flight `POST/GET /armed` `.then` calls `paintBanner` → `null.querySelector` → TypeError in the promise tail. The spec's "safe no-op" guards only on the node being *absent* (querySelector returns null on another tab), not on `_container` itself being null. Fix: guard container-truthiness first — `var b = _container && _container.querySelector(".equip-banner"); if (!b) return;` — mirroring `:368,403,672`.

### F-3 (P3): `_armedSeeded` left false after a `_armedBusy`-skipped seed → spurious GET on the next re-render
§ Frontend 4. Toggle in flight (`_armedBusy=true`), switch obs→cfg→obs resets `_armedSeeded=false`; the seed guard `!_armedSeeded && !_armedBusy` skips (busy) but never sets `_armedSeeded=true`. When the POST settles it clears `_armedBusy` without touching `_armedSeeded`, so the next SSE/poll re-render fires a spurious GET — re-entering the per-render-fetch concern Decision 7 closed. Bounded/self-correcting (P3). Fix: set `_armedSeeded = true` in the toggle `.then` after `_armedBusy=false` (a settled write is a fresh seed); state the invariant "`_armedSeeded` becomes true on a completed seed GET OR a settled write."

### F-4 (P4): null/`~` `enabled:` coerces to armed — correct fail-secure; noted for completeness. No action.

## Summary
P0: 0 | P1: 1 | P2: 1 | P3: 1 | P4: 1

STATUS: RED P0=0 P1=1 P2=1 P3=1 P4=1
