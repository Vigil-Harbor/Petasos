# Correctness Review — round 2

## Closure of round 1 findings
- correctness F-1 (ESC-02 wrong file) — **CLOSED**: now cites `config.py:_validate_tier_thresholds (L16-22)`; verified.
- correctness F-2 (ALRT-03 wrong line) — **CLOSED**: now cites `_check_cross_session_burst` buffer + `recent_sessions` (~L255-264 alerting.py); verified.
- correctness F-3 (NORM-03 count) — **CLOSED**: now "17 lowercase-only entries; Greek κ mapped, Cyrillic к unmapped"; verified `_HOMOGLYPH_TABLE` = 17.
- correctness F-4 (Plane uncached) — **CLOSED**: folded into Deferred.
- edge-cases F-1 (activate/deactivate seam, P1) — **CLOSED (core)**: PIPE-08/09/10 added + grounded (pipeline.py:196-204, _check_premium L217-233, env path L188-190). Sub-claim `petasos/__init__.py` is pure re-exports + `__version__`, no behavioral gap — informational only.
- edge-cases F-2/F-3/F-4/F-5 — **CLOSED**: three-tag D2 + sort; staleness check D4; seed-closure invariant; SCAN-07.
- conventions F-1/F-2 — **CLOSED**: canonical-source declaration; Deferred trailer.
- REOPENED: none.

## Findings
No findings.

## Verification performed
- All 3 round-1 grounding fixes verified against live source (config.py L13/16-22; alerting.py L255-264; normalize.py L48-68).
- All 4 new rows verified: PIPE-08 (claims kept only on VALID L199; _check_premium re-checks None→INVALID L221-223, expiry→EXPIRED L225-228; env auto-activate L188-190); PIPE-09 (deactivate clears both L202-204); PIPE-10 (non-atomic two-write, no lock — accurate); SCAN-07 (guard swallows only on _exc.name match L12-13/21/30).
- Assertion count = **74** (NORM6 SYN8 PIPE10 CFG5 TYP4 SCAN7 LIC9 FREQ5 ESC3 GUARD5 AUD3 ALRT4 PROF5). Matches spec claims.
- HEAD `d0af5aa`; `git log -- petasos/` confirms `44639fe` is the most recent commit touching petasos/ (later commits are PET-14 docs only). Pin valid; this is exactly the case D4's staleness check covers.
- All 10 brief Done-When map (Bucket A: 4 authorship items; Bucket B: 6 review-outcome items). SYN-01 + LIC-01/02/03 present and grounded Held.
- No internal contradictions; sort rule + 74-count + seed-closure consistent across D2/Deliverable 3/4/Bucket B.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 0 | P4: 0

STATUS: GREEN
