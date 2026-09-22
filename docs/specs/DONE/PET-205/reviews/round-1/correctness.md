# Correctness Review — round 1

## Closure of round 0 findings
N/A — round 1

## Findings

### F-1: File:line anchors cite the wrong symbols on `723cdc5`
**Severity:** P1
**Where:** spec.md:17, spec.md:19, spec.md:20, spec.md:38, spec.md:81
**Claim:** "`test_helper_never_raises_on_a_raising_inspect` (`:136`)"; "chunk-failure helper test (`:148`)"; "Initialize `inspect_failed = False` next to `head: PipelineResult | None = None` (`:130-131`)"; "`_drive_unavailable(..., "boundary")` builds today (`:668-672`): a `PipelineResult` with `scanner_results=()`"; "PET-209 sweep/floor tests (`:1005`, `:1052`)"; "`IngestionScanResult` (`:40-48`)". The `if cause is None` chain is cited as `:2426-2433`.
**Why this is wrong:** Those lines were checked with `git show 723cdc5956d024195b3b3afdde09004618266aa6:<path>`. Several citations are a different symbol, not an off-by-comment. An implementer who jumps to the number edits or preserves the wrong site. `IngestionScanResult` is a four-field frozen dataclass (`findings`, `coverage`, `head`, `errors`). The cited span `:40-48` stops on `coverage`; `head` is line 49 and `errors` is line 50. A defaulted `inspect_failed` inserted at the end of that span is a `TypeError` (non-default argument follows default). Decision 2's four-argument compatibility holds only if the field is appended after `errors`.

| Spec citation | What is actually there | Symbol the spec names |
|---|---|---|
| `tests/test_ingest_scan.py:136` | `assert last + CHUNK_CHARS >= 1_000_000` in `test_ceiling_slice_excludes_the_character_past_one_million` | `test_helper_never_raises_on_a_raising_inspect` is the `def` at **139** |
| `tests/test_ingest_scan.py:148` | blank line | `test_failed_chunk_scan_is_recorded_and_does_not_raise` starts at **149** |
| `petasos/session/ingest.py:130-131` | blank, then `errors: list[str] = []` | `head: PipelineResult \| None = None` is line **132** |
| `tests/test_reference_plugin_tool_result.py:668-672` | timeout `_Wedge` (`await asyncio.sleep(30)`, `_pipeline` install, `_result_scan_timeout` → `0.05`) | boundary arm is **673-679**; `PipelineResult(..., scanner_results=())` is line **678** |
| `tests/test_reference_plugin_tool_result.py:1005` | `assert "cause=timeout"` in `test_held_inspect_lock_still_honours_ingest_budget` | `test_sweep_error_with_high_findings_does_not_claim_full_coverage` is the `def` at **1007** |
| `docs/deployment/reference_plugin/__init__.py:2426` | `non_pii = [f for f in blocking ...]` | `if cause is None:` is line **2427** (body through **2433**) |
| `petasos/session/ingest.py:40-48` | class header through `coverage` | field list continues through `errors` at **50** |

These anchors match `723cdc5` and should stay: `_inspect_head` 141-148, shared `try` 150-165, `errors.extend` 155-159, returns 177 / 208 / 216, PET-206 checks 170-182, plugin comment 2413-2418, timeout arm 2409-2410, `_ingest_one` 527-549, `_drive_unavailable` 652, raised stub 656-661, six-cause parametrization 700-704, floor helper test 185, plugin floor test 1052. The behavior those good anchors describe was re-read: a raising `inspect` is caught, `head` is set to `None`, and `_transform_tool_result` then takes `cause=boundary` before any `ingest_flagged` emit. `Pipeline.inspect` (pipeline.py:672-684) really does not raise; it returns `scanner_results=()` (the `_types.py:252` default). The raising-double plus `inspect_failed` design matches brief contract items 2 and 3. Plane PET-205 (`8953365f-4ecb-4d85-8b31-bc487e9245b9`, Backlog) still says `head is None` → `cause=raised`; that conflict is the brief's required reconciliation, not a defect in Decision 1.

**Suggested fix:** Retarget the citations to the lines in the table, and state that `inspect_failed: bool = False` is appended after `errors` (line 50). Point the boundary sentence at 673-679 / the constructor at 678, not the timeout wedge. Point the sweep-test "do not edit" cite at 1007. Point the `cause is None` chain at 2427-2433.

## Summary
Checked at `723cdc5` (`origin/master`), not working-tree `38fa604`. The seven commits from 2026-09-20 through 2026-09-21 (PET-204, PET-206, PET-209, PET-208, PET-201, PET-200, PET-211) are that base, not later drift. Local HEAD is two archive commits ahead and those seven behind; it was not used for line checks. No `## Deferred — follow-up required` section. The cause split, flag placement on the three returns, PET-209 early return, and the real-helper regression are consistent with the brief once the anchors above are corrected.
P0: 0 | P1: 1 | P2: 0 | P3: 0 | P4: 0

STATUS: RED P0=0 P1=1 P2=0 P3=0 P4=0
