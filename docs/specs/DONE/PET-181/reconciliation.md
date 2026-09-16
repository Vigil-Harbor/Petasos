# Reconciliation Report: PET-181

> Date: 2026-09-16
> Spec: docs/specs/TODO/PET-181.spec.md
> Merge: PR #179 (`df1ef53`)
> Plane state: Done (group: completed)

## Summary

Invert-only shipped as specified. Unknown non-empty tool names are result-scanned; the seam gates on `NON_INGESTING_TOOLS`; `INGESTION_TOOLS` remains the named hook-reaching subset. No pool, no shed path, no HIGH+ recalibration. All Done-when criteria Met.

## Scope

| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/session/guard.py` | Yes | Default `ingests=True`; four exclusion rows; `NON_INGESTING_TOOLS` |
| `docs/deployment/reference_plugin/__init__.py` | Yes | Exclusion gate, cadence, EXCLUDED token |
| `docs/deployment/reference_plugin/verify.py` | Yes | Both exports required |
| `tests/test_tool_axes.py` | Yes | Invert pins, exclusion members, counts 37/8 |
| `tests/test_reference_plugin_tool_result.py` | Yes | Unknown/MCP HIGH+, exclusion, cadence |
| `tests/test_verify.py` | Yes | Missing `NON_INGESTING_TOOLS` FAIL |
| `tests/test_benchmarks.py` | Yes | Unknown-tool 8 KB measure-only |
| `CHANGELOG.md` | Yes | Own Changed/Added; PET-179 Added amended |
| `docs/deployment/hermes-desktop.md` | Yes | Inverted default documented |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-181.test-output.txt` — ship-spec test-output artifact (force-added; gitignored specs dir)

## Decisions

| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | Invert-only (no pool/shed/HIGH+ recalibration) | Confirmed | No admission-pool or shed symbols added; CHANGELOG states observability plus base-install floor until PET-178 |
| 2 | Flip table default; gate on exclusion | Confirmed | `petasos/session/guard.py:65` `ingests=True`; `:449` `NON_INGESTING_TOOLS`; plugin `_is_ingestion` `:342-346` is `canon not in _NON_INGESTING_CANON` |
| 3 | Exclusion is no externally-authored content | Confirmed | Rows `write_file`/`kanban_create`/`kanban_comment`/`patch`; `tests/test_tool_axes.py:120` eight-name pin |
| 4 | Exclude `write_file` despite lint/LSP residual | Confirmed | `write_file` in `NON_INGESTING_TOOLS`; no lint-field scan added |
| 5 | Bound `ingest_unscanned` PET-131 cadence | Confirmed | `_INGEST_UNSCANNED_LOG_EVERY_S`; `_log_ingest_unscanned` returns whether it logged; banner always concatenates |
| 6 | Blank/missing `tool_name` not scanned | Confirmed | `_is_ingestion` empty-canon floor; `test_blank_tool_name_is_not_scanned` |
| 7 | First-sighting DEBUG `PETASOS_INGEST_EXCLUDED` | Confirmed | Gate 3 `_note_ingest_skip(..., "excluded", "PETASOS_INGEST_EXCLUDED ...")` |
| 8 | Scale is a factor; measure P=8, K=1, shed 0 | Confirmed | `test_benchmark_ingestion_unknown_tool_8kb` docstring; 8-wide concurrent kept |
| 9 | Done-when 2/3 map to measurement/residuals | Confirmed | No new lock/queue/reconfigure on the result hook |
| 10 | verify.py requires both exports | Confirmed | `check_guard_exports` lists missing names; PASS names both |
| 11 | `skill_manage` cotenant overlap accepted | Confirmed | `test_bundled_security_guidance_write_targets_stay_excluded` pins `skill_manage not in NON_INGESTING_TOOLS` |

## Acceptance Criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Unregistered tool and unknown MCP both scanned | Met | `tests/test_reference_plugin_tool_result.py:452` `test_unregistered_tool_poisoned_result_is_flagged`; `:476` `test_unknown_mcp_wire_name_poisoned_result_is_flagged` |
| 2 | Concurrency posture measured at stated P | Met | `tests/test_benchmarks.py:309` unknown-tool 8 KB (K=1, shed 0, P=8 measured / P=80 residual); 8-wide concurrent kept |
| 3 | Wedged/saturated path cannot open parameter fence | Met | Invert adds no lock/queue/reconfigure; `test_read_only_tool_still_never_blocked_for_its_arguments` unedited at `:250` |
| 4 | ML posture stated as observability + base-install floor | Met | `CHANGELOG.md` PET-181 Changed; `docs/deployment/hermes-desktop.md:219-228` |
| 5 | Read-only tools still never blocked for arguments | Met | `:250` unedited; `test_argument_axis_does_not_widen`; `test_browser_navigate_is_scanned_and_still_argument_gated` |

## Test Plan

| Test | Exists? | Location |
|---|---|---|
| Unknown not in `NON_INGESTING_TOOLS` | Yes | `tests/test_tool_axes.py:110` |
| Exclusion members pinned (8) | Yes | `tests/test_tool_axes.py:119` |
| execute_code/terminal not excluded | Yes | `tests/test_tool_axes.py:124` |
| Counts 37/16/17/8/29 | Yes | `tests/test_tool_axes.py:164` |
| Unregistered HIGH+ | Yes | `tests/test_reference_plugin_tool_result.py:452` |
| Unknown MCP HIGH+ | Yes | `:476` |
| Excluded tools skip | Yes | `:499` |
| EXCLUDED emits once | Yes | `:404` |
| Blank name skip | Yes | `:509` |
| Cadence / host session_id / uncorrelated / `_agent` | Yes | `:708+` |
| MCP strip onto exclusion | Yes | `:530` |
| Missing `NON_INGESTING_TOOLS` FAIL | Yes | `tests/test_verify.py:401` |
| Unknown-tool 8 KB benchmark | Yes | `tests/test_benchmarks.py:309` |

## Wiki-ready

Decisions and comprehension worth extracting to the wiki:
- Decision 1+2: invert-only with exclusion-set gate (an inclusion frozenset cannot name a runtime MCP tool; PET-179 Decision 2 sequencing superseded only).
- Comprehension: unknown tools now scan; `INGESTION_TOOLS` is no longer the seam's membership test.

RECONCILED: yes DRIFT: 1
