# Edge-Cases Review — round 3

## Closure of round 2 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| correctness | F-1 | Spool `rule_id` anchor is the severity keyword | CLOSED | spec § Decision 3 line 70 cites `rule_id=worst.rule_id` at `reference_plugin/__init__.py:2485` and `severity=worst.severity.name` at `:2484`. At `723cdc5` those are the two keyword arguments. Agreement remains `shorten_rule_id` of the spool id versus the banner id. |
| correctness | F-2 | `pii_suppressed` counts PII that never blocked | CLOSED | spec § Decision 6 line 98 requires `finding_type == "pii"` and `ref._blocks(finding.severity)`, and rejects a non-pii blocker. Lines 98–99 state a LOW or MEDIUM `pii` finding never blocks. `_blocks` is `reference_plugin/__init__.py:382-388` at `723cdc5`. |
| conventions | F-1 | Spool `rule_id` anchor is the severity keyword | CLOSED | Same fold as correctness F-1 (spec § Decision 3 line 70). |
| conventions | F-2 | `policy_from_cells` does not read only `flagged_high_plus` and `n_eff` | CLOSED | spec § Decision 6 line 102: `wilson95` still reads `flagged_high_plus` and `n_eff`; `policy_from_cells` gains no read of the three helper fields and still reads `flagged_high_plus`, `n_eff`, `label`, `stratum`, `family`, and the shortened `rule_histogram`. Matches `policy_from_cells` at `scripts/pet200_calibrate.py:546-611` on `723cdc5`. |
| conventions | F-3 | Per-sample reader reimplements `drain_enforcement_events` | CLOSED | spec § Decision 3 lines 54–61 take the offset from `spool_size`, keep `spool_truncated` because drain treats `size <= offset` as no events (`petasos/console/_events.py:207-208`), parse with `drain_enforcement_events`, and forbid a second decoder. § Design line 145 keeps `attribute_new_events` as the pure step over those dicts. |
| conventions | F-4 | Under-30 monotonic failure is a spec-level addition | CLOSED | spec § Decision 3 line 74 names that fail-closed clock outcome as a spec-level addition so a young monotonic clock is not mistaken for cadence agreement. |
| edge-cases | — | (no findings in round 2) | CLOSED | `docs/specs/TODO/PET-218.reviews/round-2/edge-cases.md` Findings section is "No findings." |

No `## Deferred — follow-up required` section. `scale_lens` is off; no scalability report was read. Plane memory was available: PET-218 (`30fc3612-cb5e-43f8-b6b0-9cf06ed664a5`, Backlog) and PET-219 (`09461d7c-6ddf-4551-9143-b64fcabc851b`, Backlog). Anchors were checked with `git show 723cdc5956d024195b3b3afdde09004618266aa6`, not the diverged worktree.

## Findings

### F-1: Under-30 unavailable gap is specified and untested
**Severity:** P3
**Where:** spec § Decision 3 line 74 | spec § Test plan lines 165–171
**Edge case:** `time.monotonic()` still below 30 after Decision 2 clears the cadence map, and an unavailable sample has no earlier `ingest_unscanned` line for its `task_id`.
**What happens:** The agreement table makes that sample a gap, and a calibration host exits 3 instead of writing schema 2. Every new test that expects an `ingest_unscanned` line patches the plugin clock to a value at or above 30 (forced unavailable, unavailable-with-findings, cadence). An implementation that treats "unavailable and no new line" as cadence agreement whenever the clock is young still passes those pins, then publishes integer zeros on a freshly booted host.
**Why the spec misses it:** Decision 3 states the fail-closed rule. The test table only pins the patched-clock success paths and the "earlier line exists" cadence path.
**Suggested fix:** Add one test that patches the loaded plugin's `time.monotonic` to a value below 30, runs one unavailable sample with no pre-existing line for that `task_id`, and expects an observation gap (`run_table_a` raises `ObservationError`). Do not treat the missing line as cadence agreement.

## Summary

Round-2 P0/P1 items are closed. Empty, missing, malformed, foreign, duplicate, truncated, over-cap, capture-miss, and exit-3 paths fail closed instead of publishing a zero, except the documented `spool_size` collapse of an unstattable path into absence. Persistence: `atomic_write_json` stays tmp-plus-`os.replace`; exit 3 does not call it; helper columns are per-cell ints or omitted nulls, not an unbounded event log; schema 1 remains the committed report and schema 2 is the version bump. The temp spool is deleted on context exit and is not the Hermes profile spool.

P0: 0 | P1: 0 | P2: 0 | P3: 1 | P4: 0

STATUS: GREEN
