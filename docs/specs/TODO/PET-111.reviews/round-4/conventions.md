# Conventions Review — round 4

## Closure of round 3 findings
- conventions/F-1 (P3) false `time`-import grounding claim — CLOSED. Step 2 now states the verified-absent fact and ADDs the import; false PET-107-reuse clause gone (grep `reuse.*time` = none). Corroborated against the live file (0 `time` occurrences in the reference plugin).
- Cross-lens correctness/F-1 (P1) + edge/F-1 (P1) same root — CLOSED. edge/F-2 (P2 paintBanner guard), edge/F-3 (P3 `_armedSeeded`), edge/F-4 (P4) — all CLOSED.

## Findings
None.

## Silent-additions check
No new (d) additions in the round-4 delta (only the `time`-import correction, a (c) closure with rationale). Decision 1's prior-decision reconciliation re-verified accurate to PET-23 (config/rebind), PET-75 §1 (config field), PET-107 D4 (feature toggle) — the master kill switch is a new axis none contemplate. `_paths.py` purity (Decision 4), the cold-path-import idiom (`server.py:51-54`), the BUG-A allowlist (= popped keys, absent from `_BOOL_FIELDS`), and the `.switch` idiom (Decision 7) all hold.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 0 | P4: 0

STATUS: GREEN
