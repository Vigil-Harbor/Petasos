# Conventions Review — round 3

## Closure of round 2 findings
All round-2 P0/P1 CLOSED as in the author's closure_manifest. D-1–D-5 well-formed.

## Findings

### F-1: Live PET-178 forward-pointers still claim this ticket owns gate 2 and is future work
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec § Files to change (Docs); spec § Out of scope; spec § `CHANGELOG.md` Unreleased
**Suggested fix:** Add to Files to change: `petasos/session/guard.py` (retarget the gate-2 pointer to residual / a follow-up id, not PET-178) and `docs/deployment/hermes-desktop.md` (drop “Until PET-178”; keep ML-as-observability if still true). In the CHANGELOG plan: if the PET-181 / PET-179 Unreleased bullets are still unreleased, rewrite the “until / owns” clauses so they do not contradict the new PET-178 bullets. Leave P=80 and remaining ML-head coupling named as residuals (the spec already does that in its own bullets).

### F-2: CLAUDE.md Target Layout omits the new `session/ingest.py` module
**Severity:** P3
**Where:** spec § `CLAUDE.md`; spec § Files to change (Library — new helper)
**Suggested fix:** When editing CLAUDE.md, add `session/ingest.py` (`scan_ingestion_result`, `IngestionScanResult`, head/chunk/ceiling constants) to Target Layout. Optional: `formatting.py` is already missing there; do not expand this ticket into a layout backfill unless the edit is cheap.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 1 | P4: 0

STATUS: GREEN
