# PET-218 / PET-219 — Isolated real enforcement events and helper findings in calibration

Base: `origin/master` `723cdc5956d024195b3b3afdde09004618266aa6` (PR #188). Ship-spec cuts the worktree from `origin/master`. Local `master` at `38fa604` is two archive commits ahead of the pre-PET-200 divergence and does not contain `scripts/pet200_calibrate.py`. Every file:line anchor below is `723cdc5`.

Authority: `docs/specs/TODO/PET-218-219.observation-brief.md`. Plane PET-218 (`30fc3612-cb5e-43f8-b6b0-9cf06ed664a5`, Backlog) and PET-219 (`09461d7c-6ddf-4551-9143-b64fcabc851b`, Backlog). Artifact id is PET-218 because the brief filename's ticket prefix is PET-218. PET-219 is a co-ticket of this same spec, not a second spec.

Preflight: `upstream: skipped (no remote)`; `origin: behind-7 (diverged — proceeded)`; `scale-lens: off`. No `## Scale` section in the brief.

## Goal

Make one calibration run of `scripts/pet200_calibrate.py` observe two planes that the PET-200 harness currently hides. The handler return stays the authority for clean, ceiling-clean, unavailable, and visible HIGH+ annotation. A run-scoped temporary enforcement spool receives the real `ingest_flagged` and `ingest_unscanned` writer output and corroborates those outcomes. A transparent wrap of the plugin's `scan_ingestion_result` keeps each sample's `IngestionScanResult` so the report can fill `flagged_medium_plus`, `unavailable_with_findings`, and `pii_suppressed` from helper findings. Missing or inconsistent observation fails the run with a diagnostic. It never becomes a numeric zero. The published PET-200 report stays schema 1 and is not regenerated.

## Scope

| File | Region / action |
|---|---|
| `scripts/pet200_calibrate.py` | Remove the `_emit_enforcement_event` success stub in `load_plugin` (`:494`). Install a capturing wrap of the module-global `scan_ingestion_result` that `_ingest_one` calls (`docs/deployment/reference_plugin/__init__.py:540`). Add a run-scoped spool context around `run_table_a` (`:643-694`). Attribute new spool lines to `task_id`. Split helper counters off `CellAccum.add` (`:146-162`). Publish schema 2 from `_finalize_cell` (`:520-540`) only when every sample in the cell was observed. `SCHEMA_VERSION` (`:42`) becomes 2. `main` (`:707`) maps an observation failure to exit 3 and writes no report. |
| `tests/test_pet200_calibration.py` | Add the evidence tests below. Update `test_unavailable_is_not_clean` (`:139-158`) so it patches the inner scan seam and leaves the capturing wrap in place. Replace `test_ingest_flagged_counts_medium_plus` (`:337-353`) and `test_finalized_helper_only_fields_are_not_measured` (`:453-461`) with the split-plane pins. Keep the freeze, planted-positive, stratum, Wilson, and policy tests green. |
| `CHANGELOG.md` | On the `723cdc5` Unreleased PET-200 bullet, state that the committed report's helper columns stay unmeasured, and that a new schema-2 run fills them. One additional Unreleased bullet for this lane. House style: no em dashes. |

**Left alone:**

- `docs/deployment/reference_plugin/__init__.py`. Real `_emit_enforcement_event` (`:1393-1445`), `_ingest_one` (`:527-549`), `_transform_tool_result` (`:2297` onward), `_BLOCK_RANK` (`:379`), and `_INGEST_UNSCANNED_LOG_EVERY_S` (`:218`, 30.0 seconds) stay as shipped.
- `petasos/session/ingest.py`, `petasos/scanners/minimal.py`, `petasos/normalize.py`, `petasos/pipeline.py`.
- `petasos/console/_events.py` and `petasos/console/_paths.py`. The harness calls `_reset_events_state`; it does not change the writer, the 2 MB cap, or the spool schema.
- `tests/fixtures/pet200/**` and `docs/specs/TODO/PET-200.post-pet-201.report.json`.
- PET-214 ML construction, PET-216 input-shape admission, and PET-217 binary rejection.

## Decisions

### Decision 1 — One observation lane, both tickets

PET-218 and PET-219 edit the same sample loop. This spec lands them together. The handler return remains authoritative. Real events corroborate it. The helper result fills only the helper columns. A disagreement is reported. It does not rewrite the handler class.

### Decision 2 — Isolated real spool

`load_plugin` stops replacing `_emit_enforcement_event`. The loaded plugin keeps the real function, which imports `emit_enforcement_event` at call time (`reference_plugin/__init__.py:1427`).

`isolated_observation()` is a context manager in the harness:

1. Remember `petasos.console._paths._SPOOL_PATH_OVERRIDE` and `petasos.console._events._SPOOL_KEY`.
2. Remember a shallow copy of the loaded plugin's `_last_ingest_unscanned_log`.
3. Create a run-scoped temporary directory and call `_reset_events_state(path=<that file>)`. Do not pass `cap`. Do not call `set_spool_key` or `_reset_spool_key`.
4. Call the plugin's `_reset_ingest_unscanned_log()` so a previous in-process run cannot suppress this run.
5. On every exit, including an exception, write the saved cadence map back, restore `_SPOOL_KEY` to the saved object, and restore `_SPOOL_PATH_OVERRIDE` to the saved value. Delete the temporary directory.

The harness never calls `resolve_hermes_config_path` and never computes the operator Hermes spool path. `run_table_a` enters this context before the first `_transform_tool_result`.

Under pytest, `tests/conftest.py:_isolate_enforcement_spool` (`:45-69`) is a function-scoped autouse fixture. It saves `_SPOOL_PATH_OVERRIDE` and `SPOOL_CAP_BYTES`, points the spool at a temp file, and restores both. It does not touch `_SPOOL_KEY` or the plugin cadence map. Event-assertion tests construct their own plugin and enter `isolated_observation()` inside the test body, so the harness saves the autouse path and restores it on exit. The module-scoped `plugin` fixture may also enter the context for transforms that do not assert event counts. The harness does not pass a cap, so the autouse fixture remains the owner of `SPOOL_CAP_BYTES`.

### Decision 3 — Per-sample attribution

`run_table_a` keeps `task_id=f"pet200-{i}"` (`:662`). That string is the sample's correlation id. The harness passes `tool_name`, `result`, and `task_id` only. It does not pass `session_id` or `_agent`. On this call shape `_derive_session_id` (`:1048-1050`) stamps `session_id` equal to `task_id`, and `_ingest_unscanned_cadence_key` (`:1321-1336`) uses that same `task_id`.

Before each sample, `offset = spool_size(path)` (`petasos/console/_events.py:183-188`). That helper returns 0 when the file is absent or unstattable, and it never raises. After the call, `size = spool_size(path)` again.

- If the path exists and `size < offset`, record `spool_truncated`.
- If `size > SPOOL_CAP_BYTES` (2_000_000), record `spool_unbounded` and do not parse the tail.
- Otherwise read with `drain_enforcement_events(path, offset)` (`:191-230`). It reads strictly forward, skips a malformed line while advancing past it, leaves a trailing partial line unconsumed, and on a stat or read error returns `([], offset)`. There is no second UTF-8/JSONL decoder in the harness.
- A missing file is size 0. That is observed emptiness for a clean sample. `spool_size` also returns 0 on `OSError`, so an unstattable path looks like absence. A handler class that required an event then fails agreement. A clean sample treats it as observed emptiness.

`attribute_new_events` is the pure step over the dicts drain returned. It drops a `session_id` that is not this `task_id`, drops event types other than `ingest_flagged` and `ingest_unscanned`, and collapses the rest when `event_type`, `rule_id`, and `severity` are equal. One copy is kept. `scan_id` is not an identity key, because the writer mints a new id per append. When `size > offset` and drain returns no dicts, the appended bytes were malformed or still a partial line. That is not an event. Skipped lines and foreign sessions do not change counts. The agreement table uses the collapsed attributable lines only:

| Handler class | Agreement |
|---|---|
| `clean`, `ceiling_clean` | No attributable `ingest_flagged` and no attributable `ingest_unscanned`. |
| `ingest_flagged` | Exactly one `ingest_flagged` and no `ingest_unscanned`. `event["severity"]` equals the `parse_top_finding` severity. `shorten_rule_id(event["rule_id"])` equals the `parse_top_finding` rule id. |
| `unavailable` | Exactly one `ingest_unscanned` and no `ingest_flagged`, or no new attributable line when an earlier `ingest_unscanned` for this same `session_id` already exists before the offset. |

The spool stores `worst.rule_id` (`reference_plugin/__init__.py:2485`). Severity on that same call is `worst.severity.name` at `:2484`. The banner stores `shorten_rule_id` of that id (`petasos/session/formatting.py:70-73` and `:228`), which strips the prefix `petasos.syntactic.`. Severity matches on both sides because both use `Severity.name`. The planted phrase therefore agrees as spool `petasos.syntactic.injection.ignore-previous` and banner `injection.ignore-previous`, both severity `HIGH`. The raw strings are not required to be identical. `rule_histogram` keeps the shortened banner id.

The second unavailable row is the cadence case. The banner is still unavailable. The suppressed event is expected. It does not reclassify the row and it does not add a second event to the earlier sample. That row applies only when the earlier line is already in the file.

`_log_ingest_unscanned` treats a missing cadence key as `last=0.0` (`reference_plugin/__init__.py:1356-1358`). While `time.monotonic()` is below `_INGEST_UNSCANNED_LOG_EVERY_S` (30.0 seconds), the first unavailable sample after Decision 2's map clear writes no event. There is no earlier line, so that sample is a gap, not cadence agreement. The harness does not patch the plugin clock. A calibration host whose monotonic clock is still under 30 seconds exits 3 if any sample is unavailable. That fail-closed clock outcome is a spec-level addition so a young monotonic clock is not mistaken for cadence agreement, and so the plugin cadence rule stays unchanged. Tests that expect an `ingest_unscanned` line patch `time.monotonic` on the loaded plugin module to a value at or above 30 before the first unavailable call.

### Decision 4 — Fail closed when observation is incomplete

`classify_handler_return` (`:223-235`) stays the outcome label for `CellAccum.add`. Agreement failure, a capture count other than 1, `spool_unbounded`, or `spool_truncated` increments `observation_gaps` and does not increment helper counters.

`run_table_a` raises `ObservationError` after the sample loop when `observation_gaps > 0` on any cell. The exception names each gap's sample index, `task_id`, reason code, and handler class. `main` prints that diagnostic to stderr, returns exit code 3, and does not call `atomic_write_json`. Exit code 3 is an addition to the PET-200 CLI. Exit code 2 stays the existing `--remeasure` refusal. Exit code 0 stays the write path. Exit 3 does not create `--out` and does not replace a file that is already there. A pre-existing `--out` stays byte-for-byte and is not evidence for the failed run.

A unit test may call the per-sample observer and read the gap without going through `main`.

### Decision 5 — Capture the helper, leave the scan alone

`load_plugin` saves the imported function as `_observation_scan` and binds `scan_ingestion_result` to an async wrapper. The wrapper awaits `_observation_scan` with the same arguments, appends the returned object, and returns that same object. It does not replace `pipeline.inspect`, the chunk sweep, the timeout, the lock, or the failure path inside `scan_ingestion_result` (`petasos/session/ingest.py:112`).

`run_table_a` clears the capture list before each sample. Exactly one appended `IngestionScanResult` is a successful capture. Zero appends (the helper raised or timed out before returning) or more than one append is a gap (`helper_missing` or `helper_repeated`).

Tests that already replace the helper, including `test_unavailable_is_not_clean`, patch `_observation_scan`. The wrapper then captures the object `_ingest_one` actually receives.

### Decision 6 — Two metric planes

Helper marks apply only on a successful capture whose events agreed. Each mark is once per sample:

- `flagged_medium_plus`: the result contains a finding whose `severity` is one of `Severity.MEDIUM`, `Severity.HIGH`, or `Severity.CRITICAL`, and whose `finding_type` is not `pii`. Compare the enum member. `.value` is the lowercase string `"medium"` and is the wrong token. A bare string `"MEDIUM"` is also the wrong token.
- `unavailable_with_findings`: the handler class is `unavailable` and `findings` is non-empty.
- `pii_suppressed`: the handler class is `clean` or `ceiling_clean`, at least one finding has `finding_type == "pii"` and `ref._blocks(finding.severity)`, and no finding has `finding_type != "pii"` and `ref._blocks(finding.severity)`. Pass the enum member. `_blocks` keys `_SEVERITY_RANK` by that member (`reference_plugin/__init__.py:382-388`). A string severity sorts as 999 and does not block. A LOW or MEDIUM `pii` finding never enters the plugin's blocking set, so it is not a suppressed banner. PET-219's column is PII that would have blocked and was withheld.

`CellAccum.add` continues to update `n`, `unavailable_n`, `ceiling_n`, `flagged_high_plus`, `flagged_critical_only`, and `rule_histogram` from the handler class and `parse_top_finding`. It does not update the three helper fields. `rule_histogram` stores the shortened banner id. The spool line keeps the raw id. Visible HIGH+ still means a findings banner. A helper-only MEDIUM finding and a PII-only finding do not enter `flagged_high_plus` or `rule_histogram`.

`wilson95` keeps reading `flagged_high_plus` and `n_eff`. `policy_from_cells` does not gain a read of `flagged_medium_plus`, `unavailable_with_findings`, or `pii_suppressed`. It still reads the fields it reads today, including `flagged_high_plus`, `n_eff`, `label`, `stratum`, `family`, and the shortened `rule_histogram` for the existing per-rule flood.

### Decision 7 — Schema 2 means the helper columns were measured

`SCHEMA_VERSION` becomes 2. A comment beside the constant records:

- Schema 1, including `docs/specs/TODO/PET-200.post-pet-201.report.json`, stores JSON null in `flagged_medium_plus`, `unavailable_with_findings`, and `pii_suppressed`.
- Schema 2 table A stores non-negative integers there. Zero means the run observed none. Null means this cell was not fully observed, and `run_table_a` will not emit that report.
- Top-level `observation` is `complete` on a written table A report.

`CellAccum` gains `helper_samples: int = 0`. `record_helper` increments it once when capture succeeded and events agreed, including when all three marks stay 0. A gap increments `observation_gaps` and leaves `helper_samples` unchanged. After every sample in a cell agreed, `observation_gaps == 0` and `helper_samples == n`. `_finalize_cell` writes the three integers in that case. Otherwise it writes JSON null. The null branch is what a unit test sees on an accumulator that called `add` without a successful `record_helper`. `run_table_a` raises `ObservationError` before it would return a report whose helper fields are null.

`measurement` is unchanged and is not an alias of `observation`. `--limit` still sets `measurement` to `partial`. `observation` is `complete` when every sample that ran was observed, including a limited run. `build_ml_report` uses schema 2, `observation` `not_measured`, `measurement` `not_measured`, and `cells` `[]`. It does not invent helper zeros. PET-214 still owns real ML measurement.

`generated_at`, `python`, git identity, and `mean_ms` stay run metadata. New reports do not gain `scan_id` or event timestamps.

## Design

### Loader

`load_plugin` keeps the current post-init setup at `:489-497`: `_initialized`, `_init_error`, `_is_armed`, `_config`, `_pipeline`, `_ingest_lock = None`, and both loop runners. Delete only the lambda assigned to `_emit_enforcement_event`.

After `exec_module`, install Decision 5's wrapper. Initialize `_observation_results: list[IngestionScanResult]` on the module.

### Sample loop

Inside `isolated_observation()`:

```text
for each sample:
    clear _observation_results
    offset = spool size or 0
    raw = _transform_tool_result(tool_name, result=payload, task_id=pet200-{i})
    outcome = classify_handler_return(raw)
    rule_id, severity = parse_top_finding(raw)
    agreement = attribute_new_events(...)
    capture = the single IngestionScanResult, or a gap
    bucket.add(outcome, ms, rule_id, severity)
    bucket.record_helper(outcome, capture, agreement)
raise ObservationError if any bucket.observation_gaps
return the schema-2 report
```

`attribute_new_events` is a pure function of the dicts from `drain_enforcement_events`, the `task_id`, the handler class, the banner pair, and whether an earlier attributable `ingest_unscanned` exists for that id. Rule-id agreement uses `shorten_rule_id` from `petasos.session.formatting`. `record_helper` applies Decision 6 and increments `helper_samples`, or increments `observation_gaps`.

`mean_ms` stays wall time around `_transform_tool_result`, including the real helper. The wrap adds no sleep and no extra scan.

### Report shape

A written table A object matches today's keys plus `observation: "complete"` and `schema_version: 2`. Cell helper fields are ints. `rule_histogram` stays the sorted banner histogram. `policy_recommendation` is unchanged.

### Cleanup proof the tests must show

One test points `_SPOOL_PATH_OVERRIDE` at a sentinel file that already contains a marker, patches `resolve_hermes_config_path` to raise, runs one flagged sample inside `isolated_observation`, and forces an exception before the context exits. After the exception: the sentinel bytes are unchanged, `_SPOOL_PATH_OVERRIDE` is the sentinel path again, `_SPOOL_KEY` is the same object, the cadence map equals the pre-run copy, and the temporary directory is gone.

## Test plan

New tests live in `tests/test_pet200_calibration.py`. They build their own `load_plugin` and `isolated_observation` so event asserts are not coupled to the module fixture's shared spool. The module fixture still enters `isolated_observation` for the existing suite.

| Test | Pins |
|---|---|
| Planted HIGH+ sample | Findings banner, handler class `ingest_flagged`, exactly one new `ingest_flagged` whose `session_id` is the sample `task_id`. Spool `rule_id` is `petasos.syntactic.injection.ignore-previous`. Banner and `rule_histogram` are `injection.ignore-previous`. Severity is `HIGH` on the banner and the event. |
| Benign clean sample | Handler class `clean`, no attributable enforcement event, helper integers 0 when that single sample is finalized as observed. |
| Forced unavailable | Patch the plugin module's `time.monotonic` to a value at or above 30, and patch `_observation_scan` to `replace(result, errors=("boom",))`. Unavailable banner, one correlated `ingest_unscanned`, `flagged_high_plus` stays 0. |
| Unavailable with findings | Same monotonic patch and error injection on a planted payload. `unavailable_with_findings == 1`, `flagged_high_plus == 0`, no `ingest_flagged` line. |
| Helper-only MEDIUM | `Pipeline(scanners=(test_scanner,))` whose scanner returns one `Severity.MEDIUM` finding with `finding_type="encoding"` and whose `name` is not `minimal`. Short benign text. Handler stays clean, no `ingest_flagged`, `flagged_medium_plus == 1`, `flagged_high_plus == 0`. |
| PII-only | Same shape with one `Severity.HIGH` finding, `finding_type="pii"`. Handler stays clean, no `ingest_flagged`, `pii_suppressed == 1`, `flagged_high_plus == 0`, `flagged_medium_plus == 0`. |
| Cross-sample isolation | A flagged sample then a clean sample. The clean sample's class and helper integers ignore the earlier event. |
| Parser | Malformed JSON, a foreign `session_id`, and a duplicate identical `ingest_flagged` do not change the collapsed agreement for the current id. Two attributable `ingest_flagged` lines with different `rule_id`s are a gap. |
| Cadence | Patch the plugin module's `time.monotonic` to a value at or above 30, then two unavailable calls with the same `task_id`, back to back. Both handler classes are `unavailable`. The spool gains one `ingest_unscanned`. The second sample agrees via the earlier line and does not change the first sample's counts. |
| Cleanup | The sentinel proof in Design. |
| Absence | A wrapper that raises before returning a result, on a call that classifies unavailable, yields `helper_missing`. Finalized helper fields are `None`. `run_table_a` raises `ObservationError` and `main` returns 3. A pre-seeded `--out` is byte-identical afterward, and a missing `--out` is still missing. |
| Schema smoke | `run_table_a(..., limit=2)` writes schema 2, `measurement == "partial"`, `observation == "complete"`, and integer helper fields. `build_ml_report` stays `measurement` `not_measured`, `observation` `not_measured`, with empty cells. |
| Plane split | `CellAccum.add` of an `ingest_flagged` HIGH or CRITICAL banner increments visible counters only. `record_helper` is what moves `flagged_medium_plus`. |

Regression fence, unchanged assertions: manifest and template hashes, 40 planted payloads inside stratum bounds, planted head and beyond-head detection, Wilson clamp, empty / partial / unavailable / missing-S1 policy refusals, and `retain_high_plus` on a complete synthetic core.

No full 1,020-sample remeasure is part of this test command.

## Test command

Run from the ship-spec worktree, which is based on `origin/master`. Interpreter: `C:\Python314\python.exe`.

```text
C:\Python314\python.exe -m pytest tests/test_pet200_calibration.py
C:\Python314\python.exe -m ruff check scripts/pet200_calibrate.py tests/test_pet200_calibration.py
C:\Python314\python.exe -m mypy --strict scripts/pet200_calibrate.py tests/test_pet200_calibration.py
```

## Done when

- A HIGH+ sample produces a findings banner, one correlated real `ingest_flagged` spool event, and matching rule/severity accounting: severity strings are equal, and `shorten_rule_id` of the spool rule id equals the banner rule id.
- A clean sample has no findings banner and no correlated enforcement event.
- A forced unavailable sample produces the unavailable banner and one correlated `ingest_unscanned` event.
- An unavailable sample whose captured helper result still has findings increments `unavailable_with_findings` and does not become flagged.
- A helper-only MEDIUM finding increments `flagged_medium_plus` and leaves visible HIGH+ counts unchanged.
- A PII-only ingestion result increments `pii_suppressed` and produces neither a banner nor an `ingest_flagged` event.
- Cross-sample isolation, malformed lines, duplicate lines, cadence suppression, exception cleanup, and an untouched sentinel spool path are pinned.
- Frozen-manifest pins, planted positives, stratum bounds, Wilson and policy math, the HIGH+ gate, and `run_table_a(limit=2)` stay green.
- The report schema is version 2 when those helper columns carry integers. The committed PET-200 report is still schema 1.

## Out of scope

- Scanner rules, `_BLOCK_RANK`, policy thresholds, payload generation, and the frozen corpus or manifest.
- Plugin enforcement semantics, spool cap, console event schema, and the live Hermes spool.
- PET-216 and PET-217 corpus admission.
- PET-214 optional-backend measurement, a full corpus remeasure, a release, or a Hermes deployment.
- Editing `docs/specs/TODO/PET-200.post-pet-201.report.json` or the wiki checkout. `/spec-close` owns the wiki after merge.
