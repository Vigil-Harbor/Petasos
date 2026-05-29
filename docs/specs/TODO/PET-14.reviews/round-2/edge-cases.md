# Edge-Cases Review — round 2

## Closure of round 1 findings
- F-1 (activate/deactivate seam, P1) — **CLOSED**: PIPE-08/09/10 grounded to pipeline.py:196-204 + _check_premium L217-233. Seam coverage complete.
- F-2 (Held overload, P2) — **CLOSED**: D2 three tags + sort (Suspected-gap → Held* → Held) + "no bare-Held may carry a material 'but'"; all 12 named rows re-tagged Held*.
- F-3 (staleness guard, P2) — **CLOSED**: D4 file:symbol anchor + pre-execution `git rev-parse HEAD == 44639fe` check in README + ledger.
- F-4 (orphaned ledger rows, P2) — **CLOSED**: seed-closure invariant + per-lens row-claim + Bucket B bullet.
- F-5 (extras guard, P2) — **CLOSED**: SCAN-07 grounded to scanners/__init__.py L7-32.
- correctness F-1/2/3 + conventions F-1/2 — **CLOSED**.

## Findings

### F-1: Three-tag model defines no handoff for a pass that DISAGREES with a `Held*` — P2
**Where:** D2; Deliverable 4 seed-closure invariant; runbook §6.
A `Held*` asserts two things at once (happy-path holds AND a caveat exists). The four terminal statuses (confirmed/refuted/blocked-validated/accepted-risk) were defined for the binary framing. If the reviewer confirms the *caveat* is exploitable, is the row `confirmed` (happy-path verified) or `refuted` (assertion fails)? A reviewer could mark it `confirmed` and the live exploit in the caveat never lands as a finding — re-introducing the lead-burial D2/F-2 fixed, via the closure vocabulary.
**Fix:** In Deliverable 4, state: a `Held*` resolves to `confirmed` only when the happy-path holds AND the caveat is non-exploitable; if the caveat is exploitable → `refuted` (or spawn a child finding row), never `blocked-validated`. Equivalently, treat `Held*` as a Suspected-gap for closure purposes.

### F-2: Seed-closure invariant gameable via the "pass also adds new rows" escape hatch — P2
**Where:** Deliverable 4 (seed-closure); Bucket B.
The invariant checks only that no seed row stays `unverified` — not that the terminal status is evidence-justified. `accepted-risk` has no evidence bar; a Suspected-gap prime target (PIPE-02, FREQ-03) could be closed `accepted-risk`/`refuted` with the real substance laundered into an unlinked new RT-row. The gate proves row-coverage, not attack-coverage.
**Fix:** Require any seed row closed `refuted`/`accepted-risk` to carry non-empty Actual-behavior + (for accepted-risk) explicit justification; Suspected-gap seeds must record the attack attempted (D6); a seed closed `refuted` whose evidence is a new row must reference that row's Finding ID.

## Notes (no finding)
- `petasos/__init__.py` + `premium/__init__.py` are pure re-exports (no security logic); `_keys/__init__.py` empty; `public.pem` covered by LIC-04. `premium/__init__.py` also re-exports mutable `TIER3_FLOOR` (2nd path for CFG-04's gap) — behavioral gap already captured; P3 nit at most.
- CLAUDE.md says `petasos.activate(key)` but real API is `Pipeline.activate()`; PIPE-08/09/10 ground the real site — CLAUDE.md is stale (out of scope).
- LIC-05 bare-Held with "but benign" is genuinely non-material (interior non-base64url char breaks decode → INVALID). Defensible.
- Assertion count re-verified 74.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 0 | P4: 0
Both round-1 escalations genuinely closed. The two new P2s are second-order interactions introduced by the revision's own machinery (three-tag closure vocabulary; seed-closure vs new-rows), each fixable with a sentence or two in the ledger template. Non-blocking for handoff; they tighten the downstream gate.

STATUS: RED P0=0 P1=0 P2=2
