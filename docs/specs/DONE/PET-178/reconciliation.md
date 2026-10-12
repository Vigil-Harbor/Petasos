# Reconciliation Report: PET-178

> Date: 2026-09-17
> Spec: docs/specs/DONE/PET-178/spec.md
> Merge: PR #181 / `21d8dff`
> Plane state: Done (group: completed)

## Summary

PR #181 ships the layered ingest helper and the dedicated K=1 `petasos-ingest` loop. All five Done-when criteria are Met. Sixteen spec decisions are Confirmed; review-landed lock polling and `sweep_error` sit inside Decision 4/12 rather than against them. Follow-ups PET-208 / PET-205 / PET-207 / PET-206 / PET-209 stay out of this PR as specified.

## Scope

| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/session/ingest.py` | Yes | New helper |
| `petasos/__init__.py` | Yes | Re-export |
| `petasos/session/__init__.py` | Yes | Re-export |
| `petasos/session/formatting.py` | Yes | `ceiling` path + coverage line |
| `docs/deployment/reference_plugin/__init__.py` | Yes | Ingest loop, mutex, clip removed |
| `petasos/session/guard.py` | Yes | Gate-2 comment only |
| `tests/test_ingest_scan.py` | Yes | New |
| `tests/test_reference_plugin_tool_result.py` | Yes | Midpoint found; clip tests gone |
| `tests/test_formatting.py` | Yes | Ceiling-clean contract |
| `tests/test_benchmarks.py` | Yes | 8k / 100k / 1e6 + helper 8-wide serial |
| `tests/test_enforcement_events.py` | Yes | As specified |
| `tests/test_reference_plugin_block_messages.py` | Yes | Call-site pin +1 |
| `tests/test_scanner_bootstrap_structure.py` | Yes | Allowlist row |
| `CLAUDE.md` | Yes | Budget rewritten |
| `CHANGELOG.md` | Yes | Unreleased Fixed/Changed/Added |
| `docs/deployment/hardening.md` | Yes | Omitted-middle retired |
| `docs/deployment/hermes-desktop.md` | Yes | Until-PET-178 dropped |

Unexpected files in diff (not in spec):
- none

Dropped:
- `verify.py` / `tests/test_verify.py` — spec said no new sibling `check_*` row; not touched.

## Decisions

| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | Coverage plus isolation, not the pool | Confirmed | `docs/deployment/reference_plugin/__init__.py:505` — `name="petasos-ingest"`; no pool/shed/P=80 in diff |
| 2 | Flat budget | Confirmed | Helper has no source-trust split; every ingesting result uses the same layer split |
| 3 | Ceiling is 1,000,000 characters | Confirmed | `petasos/session/ingest.py:20` imports `_MAX_PARAM_TEXT_LEN`; `:80` `regime: ... "full" if total <= _MAX_PARAM_TEXT_LEN else "ceiling"` |
| 4 | Map findings to original-result coordinates | Confirmed | `ingest.py:68-74` `_map_finding`; `tests/test_ingest_scan.py:78` `test_midpoint_payload_maps_to_original_coordinates` |
| 5 | Layer split 2,048 / 65,536 / 8,192 | Confirmed | `ingest.py:22-24` `HEAD_CHARS = 2_048`, `CHUNK_CHARS = 65_536`, `CHUNK_OVERLAP_CHARS = _DECODE_MAX_BYTES` |
| 6 | Ignore host persist | Confirmed | No `tool_result_storage` subtraction in helper or plugin |
| 7 | Ingestion work runs off `_async_loop` | Confirmed | `_run_ingest_async` submits onto `_ingest_loop`; parameter path stays `_run_async` |
| 8 | Chunk overlap is `_DECODE_MAX_BYTES` | Confirmed | `ingest.py:14,24` |
| 9 | New library helper; `inspect()` stays one-shot | Confirmed | `pipeline.py` not in diff; helper calls `pipeline.inspect` once on the head (`ingest.py:134-146`) |
| 10 | Scale is a factor (N=1e6) | Confirmed | Ceiling import; CLAUDE.md curve; 8-wide inspect kept as overrun anchor |
| 11 | Executor is K=1; budget after ingest lock | Confirmed | `__init__.py:512-545` `_run_ingest_async` has no submit timeout; `_ingest_one` `wait_for` after `async with lock` |
| 12 | Narrow reconfigure exclusion | Confirmed | Private `MinimalScanner` (`ingest.py:156`); `_inspect_lock` around head only; `_apply_reconfigure` `to_thread(acquire)` (`__init__.py:1661`). Helper lock poll is a review fix of a blocking-acquire bug, not a spec drift. Cancel-safety of `to_thread(acquire)` remains PET-208 |
| 13 | One `inspect()` per result | Confirmed | `tests/test_ingest_scan.py:112` `test_inspect_is_called_once_on_the_head_prefix_with_weight_cap` |
| 14 | One `Pipeline` | Confirmed | Mutex around inspect only; sweep does not take it |
| 15 | Helper export `petasos` + `petasos.session` | Confirmed | `petasos/__init__.py:29,48,72` |
| 16 | Chunk payload 65,536 | Confirmed | `ingest.py:23` |

## Acceptance Criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | No unscanned gap below the ceiling; midpoint found; PET-170 pin deleted | Met | `tests/test_reference_plugin_tool_result.py:1343` `def test_a_payload_at_the_exact_midpoint_is_found`; no `test_a_payload_at_the_exact_midpoint_is_missed_pinned_gap` |
| 2 | Chunk-boundary straddle is found | Met | `tests/test_reference_plugin_tool_result.py:1358` `def test_chunk_boundary_straddle_is_found`; helper `tests/test_ingest_scan.py:94` |
| 3 | Latency curve measured; CLAUDE.md updated | Met | `CLAUDE.md:115-126` PET-178 budget; ship-time means ~6.1ms / ~53ms / ~453ms; evidence tests named |
| 4 | Banner and event name the coverage regime | Met | `formatting.py:47` `ResultNoticePath` includes `"ceiling"`; `test_flagged_event_records_coverage_not_truncated`; `coverage=ceiling` in `test_one_megabyte_plus_one_is_ceiling_and_returned_whole` |
| 5 | Wedged ingestion sweep cannot open the parameter fence | Met | `tests/test_reference_plugin_tool_result.py:1437` `def test_wedged_ingest_sweep_does_not_fail_open_pre_tool_call` |

## Test Plan

| Test | Exists? | Location |
|---|---|---|
| Chunk origins for 0 / HEAD / CHUNK / 1e6 / 1e6+1 | Yes | `tests/test_ingest_scan.py:63` |
| Midpoint maps to original coordinates | Yes | `tests/test_ingest_scan.py:78` |
| Straddle every origin in a 3-chunk fixture | Yes | `tests/test_ingest_scan.py:94` |
| inspect() once on head prefix with weight_cap | Yes | `tests/test_ingest_scan.py:112` |
| Ceiling slice excludes char 1_000_001 | Yes | `tests/test_ingest_scan.py:127` |
| Helper never raises on raising inspect | Yes | `tests/test_ingest_scan.py:139` |
| Private scanner is not pipeline._minimal_scanner | Yes | `tests/test_ingest_scan.py:185` |
| Failed chunk recorded (review) | Yes | `tests/test_ingest_scan.py:149` |
| Inspect lock poll (review) | Yes | `tests/test_ingest_scan.py:164` |
| Midpoint found through handler | Yes | `tests/test_reference_plugin_tool_result.py:1343` |
| Chunk-boundary straddle through handler | Yes | `tests/test_reference_plugin_tool_result.py:1358` |
| 1_000_001 is ceiling, whole result returned | Yes | `tests/test_reference_plugin_tool_result.py:1309` |
| Clean below ceiling has no banner | Yes | `tests/test_reference_plugin_tool_result.py:1374` |
| Clean above ceiling logs and banners | Yes | `tests/test_reference_plugin_tool_result.py:1387` |
| PII-only above ceiling still gets ceiling banner | Yes | `tests/test_reference_plugin_tool_result.py:1407` |
| Flagged reason has coverage= not truncated= | Yes | `tests/test_reference_plugin_tool_result.py` `test_flagged_event_records_coverage_not_truncated` |
| Isolation: wedged sweep does not fail-open pre_tool_call | Yes | `tests/test_reference_plugin_tool_result.py:1437` |
| Reconfigure wait yields _async_loop | Yes | `tests/test_reference_plugin_tool_result.py:1501` |
| Ceiling-clean banner contract | Yes | `tests/test_formatting.py:405` |
| 8-wide inspect overrun anchor | Yes | `tests/test_benchmarks.py` `test_benchmark_ingestion_result_8wide_concurrent` |
| 8-wide helper serial | Yes | `tests/test_benchmarks.py` `test_benchmark_ingestion_helper_8wide_serial` |
| PET-170 midpoint-miss pin deleted | Yes | Absent from tree |

Spec test command (PR body): 272 passed / 2 skipped. Six GitHub CI jobs SUCCESS; CodeRabbit APPROVED on `933a47c`.

## Wiki-ready

Decisions and comprehension worth extracting to the wiki:
- Decision 1: coverage plus isolation, not the pool — constrains every later concurrency ticket
- Decision 3+5: ceiling import + layer split constants — the coverage contract
- Decision 4 (review): never block the ingest loop on `Lock.acquire()` — wait_for cannot fire
- Decision 11: budget clock starts after the K=1 lock
- Comprehension: clip window retired; dedicated ingest loop; sweep_error fail-closed; PET-193 hole closed

RECONCILED: yes DRIFT: 1
