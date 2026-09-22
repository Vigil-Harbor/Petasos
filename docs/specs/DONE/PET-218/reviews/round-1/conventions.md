# Conventions Review — round 1

## Closure of round <N-1> findings
N/A — round 1

## Findings

### F-1: `_BLOCK_RANK` anchor points at the LOW rank entry
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:23
**Convention violated:** File:line anchors in this spec are pinned to `723cdc5956d024195b3b3afdde09004618266aa6` and are treated as exact.
**Evidence:** The left-alone list cites `_BLOCK_RANK` (`:376`). At that commit the dict entry on line 376 is `Severity.LOW: 3`. The constant is the next assignment:

```379:379:docs/deployment/reference_plugin/__init__.py
_BLOCK_RANK = _SEVERITY_RANK[Severity.HIGH]  # block at HIGH or worse (rank <= 1)
```

Neighboring anchors checked at the same commit do match: the emit stub at `scripts/pet200_calibrate.py:494`, `CellAccum.add` at `:146-162`, `_finalize_cell` at `:520-540`, `run_table_a` at `:643-694`, `task_id` at `:662`, `main` at `:707`, `_emit_enforcement_event` at `:1393-1445`, `_ingest_one` at `:527-549`, the `scan_ingestion_result` call at `:540`, `_transform_tool_result` at `:2297`, `_INGEST_UNSCANNED_LOG_EVERY_S` at `:218` (alias of `_DISARM_LOG_EVERY_S = 30.0`), and `scan_ingestion_result` at `petasos/session/ingest.py:112`.
**Suggested fix:** Cite `_BLOCK_RANK` as `:379`.

### F-2: Top-level `observation` is a report-contract addition
**Severity:** P3
**Where:** spec.md:101-111
**Convention violated:** Silent-addition axis, class (c). Brief item 7 authorizes a schema bump and documentation when meaning changes. It does not name a new top-level key. PET-200's report schema and `build_ml_report` today have `measurement` and no `observation`.
**Evidence:** Brief: "If schema meaning changes, bump/document the schema rather than silently repurposing a field." Decision 7 adds `observation: "complete"` on every written table A report and `observation: "not_measured"` on `build_ml_report`, while today's `measurement` key stays (`complete` / `partial` / `not_measured`). That split is reasoned in the decision (helper columns were actually observed, distinct from a limited corpus and from JSON null). It is still a new key PET-214 and any report consumer will see.
**Suggested fix:** Keep the field. Add one sentence that `measurement` is unchanged and is not an alias of `observation` (`--limit` stays `measurement: "partial"` with `observation: "complete"` when every included sample was observed).

### F-3: Exit code 3 is a new CLI contract
**Severity:** P3
**Where:** spec.md:73-77
**Convention violated:** Silent-addition axis, class (c). Brief item 6 requires an actionable failure or an explicit "not measured" mark. It does not require a new process status.
**Evidence:** Brief: "mark the affected observation unavailable or fail the harness with an actionable diagnostic; never coerce it to zero." The harness today returns 2 only for the `--remeasure` refusal (`scripts/pet200_calibrate.py:710-716`) and 0 after `atomic_write_json`. Decision 4 reserves 3 for `ObservationError`, prints the diagnostic to stderr, and skips the write. That preserves exit 2, which the brief does not mention.
**Suggested fix:** Keep exit 3. State in Decision 4 that it is an addition to the PET-200 CLI contract so a stale `--out` from an earlier successful run is not a schema-2 result, and that an existing `--out` is left in place.

### F-4: Spool restore does not name the autouse fixture it nests under
**Severity:** P3
**Where:** spec.md:39-47, spec.md:148-150
**Convention violated:** Established pytest spool isolation. `tests/conftest.py` already owns `_SPOOL_PATH_OVERRIDE` for every test.
**Evidence:** `_isolate_enforcement_spool` (autouse, function scope) saves `_SPOOL_PATH_OVERRIDE` and `SPOOL_CAP_BYTES`, calls `_reset_events_state(path)` without a cap, and restores both in `finally` (`tests/conftest.py:45-69` at `723cdc5`). It does not touch `_SPOOL_KEY` or the plugin cadence map. `_reset_events_state` itself does not clear `_SPOOL_KEY` (`petasos/console/_events.py:59-74`). The spec's context manager is the right CLI equivalent, and entering it inside a test nests correctly, but the spec never says the module fixture's context sits outside this autouse redirect.
**Suggested fix:** In Decision 2, say that under pytest the harness context is entered inside the test (or around the sample only), so it saves the autouse path and restores it on exit, and that the module-scoped fixture must not be the innermost spool owner for event assertions. No change to the cap: the spec already passes none.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 3 | P4: 0

STATUS: GREEN
