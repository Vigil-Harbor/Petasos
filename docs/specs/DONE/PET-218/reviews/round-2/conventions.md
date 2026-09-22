# Conventions Review — round 2

## Closure of round 1 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| correctness | F-1 | Flagged spool rule_id cannot equal parse_top_finding | CLOSED | spec § Decision 3 lines 70–73: `shorten_rule_id(event["rule_id"])` equals the banner id; raw strings need not match; planted pair and shortened `rule_histogram` are named. § Test plan line 166 and § Done when line 196 repeat that pair. |
| correctness | F-2 | _BLOCK_RANK anchor is the LOW rank entry | CLOSED | spec § Scope line 23 cites `:379`. At `723cdc5`, `docs/deployment/reference_plugin/__init__.py:379` is `_BLOCK_RANK = _SEVERITY_RANK[Severity.HIGH]`. |
| correctness | F-3 | helper_samples is never defined | CLOSED | spec § Decision 7 lines 115–116: `helper_samples` increments once per agreed capture, including all-zero marks; a gap leaves it unchanged; `observation_gaps == 0` implies `helper_samples == n`; null is only the direct `_finalize_cell` view, and `run_table_a` raises first. |
| correctness | F-4 | Helper severity tokens are enum names, not Severity values | CLOSED | spec § Decision 6 lines 99–101: compare `Severity.MEDIUM` / `HIGH` / `CRITICAL`; `.value` and a bare `"MEDIUM"` are rejected; `_blocks` receives the enum member. |
| edge-cases | F-1 | Banner rule id and spool rule id cannot agree | CLOSED | Same fold as correctness F-1 (spec § Decision 3 lines 70–73, § Test plan line 166, § Done when line 196). |
| edge-cases | F-2 | Helper severity tokens are not the finding's runtime type | CLOSED | Same fold as correctness F-4 (spec § Decision 6 lines 99–101). |
| edge-cases | F-3 | First ingest_unscanned is suppressed while monotonic is under 30s | CLOSED | spec § Decision 3 line 77: missing cadence key is `last=0.0`, under 30s is a gap not cadence agreement, the harness does not patch the clock, and tests patch the plugin module's `time.monotonic` to ≥ 30. § Test plan lines 168 and 174 pin that patch. |
| edge-cases | F-4 | Exit 3 leaves a previous report in place | CLOSED | spec § Decision 4 line 83: exit 3 does not create or replace `--out`; a pre-existing file stays byte-for-byte and is not evidence. § Test plan line 176 pins a pre-seeded file and a missing path. |
| conventions | F-1 | _BLOCK_RANK anchor points at the LOW rank entry | CLOSED | Same cite as correctness F-2 (spec § Scope line 23, blob line 379). |
| conventions | F-2 | Top-level observation is a report-contract addition | CLOSED | spec § Decision 7 line 117: `measurement` is unchanged and is not an alias of `observation`; `--limit` stays `measurement: "partial"` with `observation: "complete"` when every included sample was observed. |
| conventions | F-3 | Exit code 3 is a new CLI contract | CLOSED | spec § Decision 4 line 83 states exit 3 is an addition, exit 2 stays the `--remeasure` refusal, exit 0 stays the write path, and a pre-existing `--out` is left in place. |
| conventions | F-4 | Spool restore does not name the autouse fixture it nests under | CLOSED | spec § Decision 2 line 49 names `tests/conftest.py:_isolate_enforcement_spool` (`:45-69`), which matches the blob: autouse saves the override and `SPOOL_CAP_BYTES`, calls `_reset_events_state` without a cap, and does not touch `_SPOOL_KEY` or the cadence map. Event tests enter `isolated_observation()` inside the body; the module fixture is not the event-assert owner. § Test plan line 162 says the same. |

No `## Deferred — follow-up required` section. `scale_lens` is off; round 1 has no scalability report to score. Plane memory for PET-218 and PET-219 was available (Backlog; provenance PET-200 D-4 and D-2).

## Findings

### F-1: Spool `rule_id` anchor is the severity keyword
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:73 | spec § Decision 3
**Convention violated:** File:line anchors in this spec are pinned to `723cdc5956d024195b3b3afdde09004618266aa6` and are treated as exact (same rule as round-1 conventions F-1).
**Evidence:** The sentence says the spool stores `worst.rule_id` at `reference_plugin/__init__.py:2484`. At that commit the call is severity on line 2484 and `rule_id=worst.rule_id` on line 2485.
**Suggested fix:** Cite `rule_id=worst.rule_id` as `:2485`. Leave `:2484` for the severity `.name` claim if that line is cited at all.

### F-2: `policy_from_cells` does not read only `flagged_high_plus` and `n_eff`
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:105 | spec § Decision 6
**Convention violated:** Reuse of the existing policy function. The shipped function is the source of truth for "unchanged."
**Evidence:** spec § Decision 6 says `policy_from_cells` and `wilson95` keep reading `flagged_high_plus` and `n_eff` only. `wilson95` is that pair. `policy_from_cells` (`scripts/pet200_calibrate.py:546-611` at `723cdc5`) also reads `label`, `stratum`, `family`, and `rule_histogram`, and the per-rule flood uses `count / n_eff >= 0.03` (lines 602–610). § Design line 154 says `policy_recommendation` is unchanged, and § Done when line 203 says policy math stays green. "Only" contradicts both.
**Suggested fix:** Say the two functions do not gain a read of `flagged_medium_plus`, `unavailable_with_findings`, or `pii_suppressed`. State that `policy_from_cells` still reads `flagged_high_plus`, `n_eff`, and the shortened `rule_histogram` for the existing flood rule.

### F-3: Per-sample reader reimplements `drain_enforcement_events`
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:55-63 | spec § Decision 3; spec.md:148 | spec § Design
**Convention violated:** Reuse versus a second JSONL decoder. PET-200 D-2 / Plane PET-219 say to drain via `_events`. `drain_enforcement_events` and `spool_size` are already the spool read seams.
**Evidence:** At `723cdc5`, `petasos/console/_events.py:183-188` `spool_size` returns 0 when the file is missing and never raises. `drain_enforcement_events` (`:191-230`) reads strictly forward from a byte offset, skips a malformed line, does not consume a trailing partial line, and on a stat error returns `([], after_offset)`. The spec's bullet list decodes UTF-8, skips non-objects, and treats a missing file as emptiness without naming either function. PET-219's suggested fix: "Keep the real `_emit_enforcement_event` and drain via `_events`." The brief requires attributable, bounded reads; it does not authorize a second decoder. Drain alone is not enough: it treats `size < offset` as no new events, while this spec must record `spool_truncated`, and it does not apply the session, type, or collapse rules.
**Suggested fix:** Take the offset and the cap check from `spool_size` and `SPOOL_CAP_BYTES`. Parse new lines with `drain_enforcement_events`. Keep `attribute_new_events` as the pure step over those dicts (session filter, type filter, collapse, agreement table). Do not describe a second UTF-8/JSONL loop.

### F-4: Under-30 monotonic failure is a spec-level addition
**Severity:** P3
**Where:** spec.md:77 | spec § Decision 3
**Convention violated:** Silent-addition axis, class (c). Not a behavior defect; the paragraph already has the mechanism.
**Evidence:** The brief requires the real writer, says cadence suppression must not change the current row, and says missing observation fails rather than becoming zero. It does not name `time.monotonic` or a host-uptime failure. Decision 3 adds: after the map clear, a calibration host whose monotonic clock is still under 30 seconds exits 3 if any sample is unavailable, and the harness does not patch that clock. Tests patch it. That is an operational contract past the brief, with rationale in the decision (do not change the plugin cadence rule).
**Suggested fix:** Keep the rule. Add one clause that this fail-closed clock outcome is a spec-level addition so a later reader does not treat a young monotonic clock as an accidental gap.

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 1 | P4: 0

STATUS: GREEN
