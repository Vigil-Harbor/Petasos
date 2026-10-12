# PET-178 — Retire the ingestion scan window: full-coverage result scanning with no unscanned gap

**Status:** Backlog · **Priority:** medium · **Assignee:** Devin Matthews
**Created:** 2026-08-06 · **Plane:** PET-178 (4564b436-896f-4190-a38c-7126cb4717f2, Backlog)
**Origin:** Plane ticket opened 2026-08-06 after PET-170 shipped the 8,000-character head/tail window and pinned the mid-window gap. A 2026-09-16 comment on this ticket inherited PET-181's fenced pool, shed, P=80, and gate-2 dict skip; this brief takes layered coverage plus loop isolation and leaves those as residuals. Retrieved from shared memory (`plane_work_item`) on 2026-09-16; Plane body confirmed via tracker.

## Problem

PET-170 scans an 8,000-character window of each ingestion-tool result: head plus tail, with a 512-char overlap extending head coverage past the boundary and a truncation marker between the two halves. For any result larger than the window, **the middle is never scanned by anything**, and PET-170 pins that gap with a test rather than closing it.

That is a poor place to leave it. An attacker who knows the cap (it ships on PyPI, so they do) plants the payload at the midpoint of a large file and the seam sees nothing. The banner is honest about it, saying what was scanned and never claiming the content is clean, but honesty about a hole is not a fix.

## Why it matters

The 8,000 figure was sized against *full-pipeline* latency. Both ML backends truncate around 512 tokens and neither chunks, so past roughly the first 1,500 to 2,000 characters only MinimalScanner is contributing. The window was buying a bounded number of MinimalScanner passes, not ML coverage. Full syntactic coverage of a 100 KB result is roughly a 50 ms proposition on PET-170's numbers, not a 6 ms clip.

After PET-181, unknown tools are result-scanned. Multiplying that volume on the shared `_async_loop` without isolation makes PET-170's recorded residual worse: a Stage 2 regex wedge on attacker-controlled result text occupies the loop, `_pre_tool_call`'s `_guard.evaluate` times out, and the parameter-side blocking fence fail-opens for the duration.

## Scope (verified against current files, 2026-09-16)

| Path | Current | Change |
|---|---|---|
| `docs/deployment/reference_plugin/__init__.py` | `_MAX_RESULT_SCAN_CHARS = 8_000` (`:2160`); `_clip_result` head+tail with `_RESULT_SCAN_HEAD_BIAS = 512` (`:2182-2198`); `_transform_tool_result` clips then `_run_async(pipeline.inspect(...))` on the shared `_async_loop` (`:2288-2338`); `_run_async` default 15 s (`:451`); `_pre_tool_call` fail-opens on timeout (`:1963-1966`) | Stop clipping below 1,000,000 characters. Call a library helper for the layered sweep. Run that work on a dedicated K=1 loop or worker thread, not `_async_loop`. Mutex only around `inspect()` (head + parameter scans). Banner and event name the coverage regime. Above 1e6, disclose; never claim clean |
| `petasos/pipeline.py` | Stage 2 is a bare `await effective_scanner.scan(...)` (`:719-723`). `inspect()` is one-shot. ML path uses `asyncio.wait_for` (`:254`) | `inspect()` stays one-shot. Do not chunk inside `inspect()`. Do not add Stage 2 `wait_for` as the isolation mechanism |
| `tests/test_reference_plugin_tool_result.py` | `test_a_payload_at_the_exact_midpoint_is_missed_pinned_gap` (`:1281`) pins the hole | Delete that pin. Replace with a test that plants a payload at the midpoint of a large result and finds it. Chunk-boundary straddle is found. Original-result offsets. Clean truncated-above-ceiling still honest |
| `tests/test_benchmarks.py` | 8 KB / 100 KB / 8-wide concurrent `inspect()` cases (`:240`, `:275`, `:297`); 100 KB is flat because the window bounds it | Measure the latency curve by result size up to 1,000,000 characters (base-install syntactic sweep + ML head). Keep 8-wide concurrent. Update CLAUDE.md to match rather than quietly exceed |
| `CLAUDE.md` | Ingestion-path budget is **12ms of scan** at the 8,000-char cap (`:142-148`); 8-wide overrun documented | Replace the 8k/12ms figure with the measured curve and the new ceiling |
| `CHANGELOG.md` | Unreleased records PET-181 invert-only; ML is observability plus a base-install floor until PET-178 | Own Changed/Fixed: the 8k mid-window gap is closed below 1e6; layer split and isolation named; remaining ML-head coupling and P=80 residual disclosed |

## Decisions carried forward

1. **Coverage plus isolation, not the pool (Q1 B).** Layered scans and loop isolation ship here. Admission pool, shed path, P=80 width, and gate-2 dict skip stay residuals — why: four PET-179 reviews died on the pool; invert already shipped, so a result-scan wedge must not fail-open the parameter fence.
2. **Flat budget (Q2 A).** No PET-180 source-trust split. Every ingesting result gets the same layer split — why: PET-180 is a different policy; this hole stays open if the two couple.
3. **Ceiling is 1,000,000 characters (Q3 A).** Same as `_MAX_PARAM_TEXT_LEN`. Above it, name the regime. Never claim clean — why: one number for both axes; banner honesty covers the rest.
4. **Map findings to original-result coordinates (Q4 A).** Chunk spans are not the operator-facing coordinates — why: the midpoint pin is the acceptance test; mapping is how you prove it.
5. **Layer split (Q5 A).** Full `inspect()` on a short head sized to the ML truncation ceiling (~2 KB; spec measures). Overlapping syntactic chunks on the rest, up to the ceiling — why: PET-170 already measured ML as head-only; wrappers pass full `text` and do not set `max_length` themselves.
6. **Ignore host persist (Q6 B).** This hook covers the payload it is given. Follow-up `read_file` is a separate scan. Do not subtract Hermes `tool_result_storage` self-coverage — why: that file is not in this repo.
7. **Ingestion work runs off `_async_loop` (Q7 B).** Own executor so a result-scan wedge cannot starve `_pre_tool_call` — why: Stage 2 is a synchronous regex behind a bare await; `wait_for` cannot interrupt it; PET-170 Out of scope 12 named this mitigation.
8. **Chunk overlap ≥ 8192 (Q8 A).** That is `_DECODE_MAX_BYTES`, the decode-rescan carrier — why: a blob split on a cut must still decode inside one chunk; 512 was a round number.
9. **New library helper; `inspect()` stays one-shot (Q9 C).** The plugin calls the helper. Parameter scans and playground `inspect()` do not chunk — why: N `inspect()` calls would multiply the PET-176 weight step and change every caller.
10. **Scale is a factor (Q10 A).** Target: 1,000,000 characters. Dimensions: 8-wide concurrent `inspect()`; base-install syntactic cost vs ML head. P=80 is a residual, not this N.
11. **Executor is K=1 (Q11 A).** One dedicated loop or worker thread. Ingestion is serialized with itself, not with parameter scans — why: width is the fenced pool.
12. **Narrow reconfigure exclusion (Q12 A).** Snapshot or wait so a live `reconfigure` cannot tear the pipeline under an in-flight helper run. Not admission, not shed — why: the second executor makes the race real; the pool's lock design stays fenced.
13. **One `inspect()` per result (Q13 A).** That is the head. Chunks are `MinimalScanner.scan` only. The helper merges findings, maps offsets, and the plugin emits one banner and one event — why: `weight_cap` is one step per `inspect()` call; per-chunk `inspect()` floods the backstop.
14. **One `Pipeline` (Q14 A).** Mutex only around `inspect()` (the short head, and parameter scans). The helper's syntactic sweep uses its own `MinimalScanner` and does not take that mutex. Remaining ML-head coupling (including the shared 30 s breaker) is recorded, not split — why: a mutex held for a 1 MB Stage 2 wedge would again starve the parameter fence; two pipelines dual-load ML.

## Done when

- No unscanned gap below the stated ceiling, pinned by a test that plants a payload at the midpoint of a large result and finds it. This is the direct inversion of PET-170's `test_a_payload_at_the_exact_midpoint_is_missed_pinned_gap`, which should be deleted rather than edited.
- Chunk-boundary soundness: a payload straddling any boundary is found.
- The latency curve by result size is measured and recorded, and the ingestion budget in CLAUDE.md is updated to match rather than quietly exceeded.
- The banner and the event state which coverage regime applied.
- The loop-contention interaction is fixed: a wedged ingestion sweep cannot open the parameter-side blocking fence.

## Out of scope

- Admission pool, shed path, and the P=80 saturation fix (Q1 B).
- Gate 2 non-string widening (`vision_analyze` / `browser_vision` dict skip) (Q1 B).
- PET-180 source-trust tiers (Q2 A).
- Measuring or subtracting Hermes persist / `read_file` self-coverage (Q6 B).
- Bounding Stage 2 in-pipeline (`asyncio.wait_for` on MinimalScanner) as the isolation mechanism (Q7 A rejected).
- Chunking inside `Pipeline.inspect()` (Q9 B rejected).
- A thread pool of size K (Q11 B rejected).
- `inspect()` once per chunk (Q13 B rejected).
- Two `Pipeline` instances / second ML load (Q14 B rejected).
- New-population HIGH+ recalibration (PET-200).
- Span-level redaction (PET-177); this ticket maps offsets, it does not redact.
- Exclusion-latch isolation from the 512 drop-oldest map (PET-203).
- Re-opening invert (PET-181 Done).
- Annotate-never-withhold (PET-170 Decision 6): the handler still returns the whole result; clipping governs only what is scanned.

## Scale

**Factor:** yes
**Target:** 1,000,000 characters
**Dimensions:** 8-wide concurrent `inspect()`; base-install syntactic sweep cost vs ML head. Gateway offered load P=80 is a residual, not this target.

## Risks / decisions

1. Helper export location (`petasos` + `petasos.session` vs `petasos.session` only) — spec author pins this.
2. Chunk payload length besides the 8192 overlap — spec author pins this.

## References

- `docs/deployment/reference_plugin/__init__.py:2160` — `_MAX_RESULT_SCAN_CHARS = 8_000`.
- `docs/deployment/reference_plugin/__init__.py:2182` — `_clip_result` head + tail; omitted middle unscanned.
- `docs/deployment/reference_plugin/__init__.py:451` — `_run_async` submits onto the shared `_async_loop`.
- `docs/deployment/reference_plugin/__init__.py:470` — `run_coroutine_threadsafe(coro, _async_loop)`.
- `docs/deployment/reference_plugin/__init__.py:1963` — `_pre_tool_call` `_guard.evaluate` via `_run_async`; timeout/exception allows the call.
- `docs/deployment/reference_plugin/__init__.py:2252` — gate 2 skips non-string results (`PETASOS_INGEST_NOT_STRING`).
- `docs/deployment/reference_plugin/__init__.py:2288` — clip then `pipeline.inspect` on the shared loop.
- `tests/test_reference_plugin_tool_result.py:1281` — midpoint gap pinned, not closed.
- `petasos/pipeline.py:719` — Stage 2 bare `await effective_scanner.scan(...)`.
- `petasos/pipeline.py:254` — ML `_scan_one` uses `asyncio.wait_for`.
- `petasos/session/guard.py:484` — `_MAX_PARAM_TEXT_LEN = 1_000_000`.
- `petasos/session/guard.py:912` — `scan_weight_cap`: one capped step per `inspect()`, never a sum of findings.
- `petasos/scanners/minimal.py:420` — `_DECODE_MAX_BYTES = 8192`.
- `petasos/scanners/llm_guard.py:397` — wrapper passes full `text`; no in-repo 512-token cap.
- `docs/specs/DONE/PET-170/spec.md:441` — Decision 6: 8,000-char window; ML coverage stops ~2 KB.
- `docs/specs/DONE/PET-170/spec.md:933` — Out of scope 4: span-level redaction and original-offset mapping.
- `docs/specs/DONE/PET-170/spec.md:945` — Out of scope 12: bound Stage 2 or own executor.
- `docs/specs/DONE/PET-181/spec.md:308` — PET-178 owns cheaper/layered scans, pool, shed, P=80.
- `docs/specs/DONE/PET-181/spec.md:313` — Gate 2 non-string widening fenced to PET-178.
- `CLAUDE.md:142` — ingestion-path 12 ms / 8,000-char budget.
- Wiki: `projects/petasos/state.md` (PET-181 invert-only; until PET-178, ML is observability plus a base-install floor).
- Plane: PET-178 Backlog (`4564b436-896f-4190-a38c-7126cb4717f2`); PET-200 HIGH+ recalibration; PET-180 source-trust.
- Interview: 3 rounds, exit round-cap.
