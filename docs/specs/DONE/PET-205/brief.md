# PET-205 - make real-helper inspect failure attribution explicit

Prepared for builder dispatch. Base `723cdc5956d024195b3b3afdde09004618266aa6` (PR #188 merged). This is a narrow implementation brief; do not revive the ticket's original five-cause rewrite without first reconciling it against the landed helper.

## Problem and scope

The original silent-pass-through claim no longer reproduces. `scan_ingestion_result()` catches an exception from the real `pipeline.inspect()`, returns `head=None` plus `errors`, and `_transform_tool_result()` emits the scan-unavailable banner and `ingest_unscanned` event. The remaining defect is attribution: that real-helper path currently falls through to `cause=boundary`, while `cause=raised` is covered only by replacing the helper itself with a raising stub.

Own the smallest necessary change in `petasos/session/ingest.py`, `docs/deployment/reference_plugin/__init__.py`, and targeted ingestion/reference-plugin tests. Preserve content pass-through, banner wording, event cadence, timeout behavior, scan budget, cancellation, ceiling accounting, and PET-209's rule that any unavailability wins before findings are surfaced.

## Required contract

1. Add a regression that drives a raising `pipeline.inspect()` through the real `scan_ingestion_result()` and the real `_transform_tool_result()` path. It must prove there is no silent pass-through: the return contains the scan-unavailable annotation, the original content is intact, and one bounded `ingest_unscanned` reason is emitted.
2. Reconcile the cause vocabulary before changing code. If `boundary` is the intended stable operator category, amend PET-205's acceptance language and pin it explicitly. If an inspect exception must be distinguishable from an empty/malformed boundary result, carry a typed or explicit helper outcome to the plugin and emit a truthful stable cause such as `inspect_error`. Do not infer cause by parsing exception strings.
3. Keep distinct existing outcomes distinct: `no_pipeline`, outer/helper `raised`, `timeout`, genuine `boundary`, `floor_error`, and `sweep_error`. Do not collapse floor or sweep errors into the new inspect category.
4. When an inspect failure and syntactic findings coexist, unavailability still wins and no `ingest_flagged` event is emitted. This is PET-209's precedence and is not open for retuning here.
5. The helper remains cancellation-correct and never-throws for ordinary scan failures. Do not move the scan back onto `_run_async`, change lock ownership, or widen the timeout surface.

## Required evidence

- Real helper + raising inspect: annotated unavailable result, exact original suffix, one `ingest_unscanned` event, truthful cause, no `ingest_flagged` event.
- The same case with a syntactic HIGH+ finding elsewhere in the payload: unavailable still wins.
- Genuine boundary result remains independently classified; existing `floor_error`, `sweep_error`, `timeout`, `no_pipeline`, and helper-stub `raised` pins remain green.
- Existing cancellation, loop-isolation, lock/reconfigure, ceiling, and cadence tests remain green.
- Focused tests plus the supported lint/type/test checks for the touched surface.

## Return

Return the reconciled cause contract, PR/head, exact production and test changes, checks, review dispositions, and any Plane/spec wording that must change. Explain why the chosen category is operator-truthful. No calibration-harness work, threshold changes, release, or Hermes deployment.
