# Correctness Review — round 1

## Findings

### F-1 (P1): `_pre_tool_call` rewrite silently changes genuine-init-failure semantics and ships a dead branch
spec § Design step 3 (reference_plugin); current code `reference_plugin/__init__.py:444-453`.
The existing behavior on a genuine (non-"disabled") init failure is **allow / pass-through** (`:447-449` returns None with a debug log), NOT fallback. The fallback scanner is reached only in the init-in-progress window (`:453`). The spec's rewrite flips genuine-failure → fallback-scan (unflagged behavior change) and makes both if/else arms identical (dead `if _init_error:` test). Fix: preserve the current three-way init handling exactly (drop only the `_init_error == "disabled"` lines `:445-446`), then add the armed gate.

### F-2 (P2, Pre-ship recommended: yes): document the surviving `_init_error` readers
`_deferred_init` re-entry guard `:148` and `_ensure_initialized()` `:362` both still read `_init_error`. After retiring the "disabled" *value*, they behave correctly (genuine failure still latches), but the spec's "verified" claim doesn't enumerate them. Add a line to Decision 3 noting `_init_error` survives as the genuine-failure latch (`:148`,`:362`); only the "disabled" value (`:162`/`:445`) is retired.

### F-3 (P3): minor stale/imprecise anchors
`Pet.api` opens at `petasos.js:247` (spec cites `:284-290`, the tail). The no-innerHTML rule is true for content injection only — `renderDashboard` uses `container.innerHTML = ""` / `contentEl.innerHTML = ""` to *clear* (`:579,643,647`); the banner will need the clear idiom too. Reword to "no innerHTML string assignment with dynamic content; `el.innerHTML=''` to clear is the existing idiom." Correct `Pet.api` anchor to `:247-291`.

### F-4 (P3): name the concrete enforce trigger for the live-disarm test
Done-when 2 test relies on `_run_async(_guard.evaluate(...))` driving the real guard. Name the trigger (a dangerous tool with an injection-pattern param MinimalScanner rates HIGH → block) so the implementer doesn't reach for tier-3 frequency state; note the async loop must spin up (no monkeypatch of `_run_async`).

## Verified-correct
`_paths` signatures + never-raises D3 hold; BUG-A real (`server.py:71` whole-section replace; `enabled`/`host_id` never round-tripped; allowlist fix correct); BUG-B real; two-process file-channel design sound under Option A; no symbol collisions (`read_armed`/`write_armed`/`_is_armed`/`/armed` absent today; "disabled" sentinel has no external reader); route surfaces correct (`/api/armed` standalone, bare `/armed` embedded, `Pet.api.baseUrl="/api"`); Plane PET-111 matches brief.

## Summary
P0: 0 | P1: 1 | P2: 1 | P3: 2 | P4: 0

STATUS: RED P0=0 P1=1 P2=1 P3=2 P4=0
