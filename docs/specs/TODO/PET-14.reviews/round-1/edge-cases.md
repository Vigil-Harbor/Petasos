# Edge-Cases Review — round 1

## Findings

### F-1: `Pipeline.activate()/deactivate()` license hot-swap + `petasos/__init__.py` API have no assertion — P1
**Where:** Design assertion tables — no row for `activate`; brief Threat Model category 5; CLAUDE.md "Pipeline never reconstructed on key change."
The hot-unlock surface (`pipeline.py:196` activate, `:202` deactivate, `PETASOS_LICENSE_KEY` env path) is the direct target for brief threat category 5 (bypass premium gating, elevate tier). LIC-* grounds token validation but nothing asserts the call site that consumes validated claims and flips premium enforcement live. No seeded assertion for: (a) activate() re-validates / fails closed on INVALID/EXPIRED without enabling features; (b) deactivate() leaves no residual; (c) enable/disable cannot interleave with in-flight inspect() to leave hooks half-wired. `petasos/__init__.py` (public API + `__version__`) appears in neither brief scope table nor any assertion.
**Fix:** Add 2–3 assertions (e.g., PIPE-08/09/10) grounding pipeline.py:196/202 + _check_premium. Tag Suspected-gap pending review.

### F-2: `Held` tag overloads a third "Held-but-caveated" state — P2
D2 defines two confidence values, but ≥10 rows are written `Held — but <material caveat>` (SYN-07, PIPE-03, CFG-04, LIC-04, LIC-08, ESC-01, ESC-03, NORM-05, SCAN-03, FREQ-05). Rendered as a one-word priority hint + sort key, the caveat is lost — a caveated-Held like SYN-07 (fail-open-at-scanner, -O-stripped assert) sorts below clean Held rows and may never be reached in a time-boxed lens.
**Fix:** Add a third tag `Held*`/`Held-conditional` sorting between Suspected-gap and clean Held, OR re-tag every `Held — but …` row as Suspected-gap. Make the render/sort rule explicit.

### F-3: Grounding pinned to 44639fe but ships against moving HEAD with no staleness guard — P2
Every citation pins `~Lnn` at 44639fe; current HEAD is d0af5aa (diff empty today). The cross-model pass runs downstream, possibly after petasos/ moves, silently drifting line offsets.
**Fix:** Add a mandatory pre-execution step to README/findings: verify `git rev-parse HEAD == 44639fe`; else `git diff --stat 44639fe HEAD -- petasos/` and re-ground cited files. Make `file:symbol` the load-bearing anchor, line numbers approximate.

### F-4: No tripwire for "cross-model reviewer leaves seeded ledger rows unowned" — P2
Lens→group mapping is many-to-many; each seeded row has one Lens field. Bucket B's "≥50 verified" can be met while some seeded `unverified` rows are never touched (the pass also adds new rows). Silent coverage hole at the release gate.
**Fix:** Add Bucket B exit invariant: every pre-seeded `unverified` row must reach a terminal status (confirmed/refuted/blocked-validated/accepted-risk); add a runbook step requiring each lens to claim its owned rows.

### F-5: `scanners/__init__.py` extras-import isolation guard unasserted — P2
`scanners/__init__.py:11-32` swallows ImportError only when `_exc.name` matches the expected extra; an extra installed-but-broken raising `ImportError(name=extra)` is silently swallowed → scanner absent → feeds PIPE-02/SCAN-04 fail-open with no distinct signal.
**Fix:** Add one SCAN assertion: import-guard distinguishes 'extra absent' from 'intended scanner failed to load'. Tag Suspected-gap.

## Summary
P0: 0 | P1: 1 | P2: 4 | P3: 0 | P4: 0
Assertion count 70 ≥ 50 (claim holds). All 15 brief scope modules map to a group. Bundled public key covered via LIC-04. Bucket A/B split has no orphaned brief requirement. Spot-checked groundings (LIC-07, NORM order/table, GUARD-05) accurate.

STATUS: RED P0=0 P1=1 P2=4 P3=0 P4=0
