# PET-218 / PET-219 - observe real enforcement events and helper findings in calibration

Prepared for builder dispatch. Base `723cdc5956d024195b3b3afdde09004618266aa6` (PR #188 merged). Treat these tickets as one observation-lane change because both wrap the same PET-200 sample execution and report row.

## Problem and scope

The calibration harness currently replaces `_emit_enforcement_event` with a success lambda and classifies only the handler return. That is sufficient for the HIGH+ ship gate, but it cannot corroborate operator-visible events and cannot populate helper-only MEDIUM+, unavailable-with-findings, or PII-suppression columns. PET-218 supplies an isolated real event spool; PET-219 captures the real helper result without replacing scanning behavior.

Own `scripts/pet200_calibrate.py`, `tests/test_pet200_calibration.py`, and only the smallest supporting fixtures or report-schema documentation. Do not change scanner rules, `_BLOCK_RANK`, policy thresholds, the frozen corpus/manifest, payload generation, plugin enforcement semantics, or the live Hermes spool.

## Required contract

1. **Isolated real spool.** Create a run-scoped temporary spool and point `petasos.console._events` at it through `_reset_events_state(path=...)` before loading/running the plugin. Use the real event writer. Restore the prior override and key state on every exit path; never resolve or write the operator's live Hermes spool.
2. **Per-sample event attribution.** Give each sample a unique correlation identity and read only events attributable to that sample. A prior sample, cadence suppression, malformed line, or duplicate must not change the current row. Keep spool parsing bounded and deterministic.
3. **Authority split.** The handler return remains authoritative for `clean`, `ceiling_clean`, `unavailable`, and visible HIGH+ annotation. Real `ingest_flagged` / `ingest_unscanned` events corroborate those operator-visible outcomes and expose disagreements; they do not silently override the return classifier.
4. **Capture, do not stub, the helper.** Wrap the module-global `scan_ingestion_result` invoked by `_ingest_one`, await the original function, retain that sample's `IngestionScanResult`, and return it unchanged. Do not replace `pipeline.inspect`, the syntactic sweep, timing, lock, or failure behavior.
5. **Separate metric planes.** Derive helper-only fields from the captured result: MEDIUM+ findings, whether an unavailable sample also had findings, and PII findings suppressed from the visible banner/event. Derive HIGH+/CRITICAL visible fields and rule histogram from the existing handler/event plane. Do not count helper-only MEDIUM or PII as `ingest_flagged`.
6. **Absence is explicit.** If helper capture or spool evidence is missing/inconsistent, mark the affected observation unavailable or fail the harness with an actionable diagnostic; never coerce it to zero. Preserve the distinction between zero observed and not measured.
7. Keep the report deterministic apart from existing time/identity metadata. If schema meaning changes, bump/document the schema rather than silently repurposing a field.

## Required evidence

- A HIGH+ sample produces a findings banner, one correlated real `ingest_flagged` spool event, and matching rule/severity accounting.
- A clean sample has no findings banner and no correlated enforcement event.
- A forced unavailable sample produces the unavailable banner and one correlated `ingest_unscanned` event; a variant with helper findings increments `unavailable_with_findings` without becoming flagged.
- A helper-only MEDIUM finding increments `flagged_medium_plus` while leaving visible HIGH+ counts unchanged.
- A PII-only ingestion result increments `pii_suppressed` while producing neither a banner nor `ingest_flagged` event.
- Cross-sample isolation, malformed/duplicate spool records, cleanup on exception, and proof that the live/default spool path is untouched.
- The original frozen-manifest pins, planted positives, stratum bounds, Wilson/policy math, HIGH+ gate, and a limited calibration smoke remain green.

## Coordination and sequencing

Land PET-218 and PET-219 together or in one tightly ordered stack with a single owner for `pet200_calibrate.py`. Keep PET-216/217 out of this diff; they should follow once the observation row is stable. PET-214 real optional-backend measurement follows after this lane so it consumes trustworthy observations rather than duplicating them.

## Return

Return the report-schema delta, PR/head, event/helper attribution design, cleanup proof, tests/checks, a limited before/after sample report, and review dispositions. No full corpus remeasurement claim, optional-backend enablement, release, or Hermes deployment.
