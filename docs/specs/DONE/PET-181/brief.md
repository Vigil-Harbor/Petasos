# PET-181 — Invert the ingestion axis default: scan unknown tools by default, with the concurrency budget to afford it

**Status:** Backlog · **Priority:** high · **Assignee:** Devin Matthews
**Created:** 2026-08-06 · **Plane:** PET-181 (082ef382-60ea-4027-a3a6-6eda00e243ef, Backlog)
**Origin:** Split out of PET-179 on 2026-08-06 after four rounds of spec review. PET-179 kept the structural half (two classification axes, browser family, dead-name corrections); this ticket owns the policy half. Sequenced after PET-178 in the PET-179 decision; PET-178 is still Backlog. Retrieved from shared memory (`plane_work_item`) on 2026-09-15.

## Problem

On the result axis an unrecognised tool name means **not scanned**. That default cannot be made correct by enumeration: MCP servers register tools at runtime from per-deployment manifests, so the ingestion set is unbounded and varies per install. Enumeration already failed at the worst possible scale: of `READ_ONLY_TOOLS`' 17 entries, 12 do not resolve to a registered Hermes tool, and the browser family was absent entirely (that specific hole is PET-179's).

The fix is to invert: unknown means scanned, so a tool Hermes adds next release, or an MCP server registers at runtime, is covered without a Petasos change. Both axes would then fail toward scrutiny.

## Why it matters

The inversion takes the ingesting fraction from roughly 4/72 tools (pre-PET-179) / 17 named tools (post-PET-179) to roughly 68/72, plus every runtime MCP name. Offered concurrency is not 8: `_MAX_TOOL_WORKERS = 8` is per agent loop, the plugin's executor is a process global, and the gateway dispatches concurrent turns and in-process `delegate_task` children, so P = 8 × concurrent agent loops (P=80 stock gateway, P=320 with default subagents). A single-threaded ingestion loop saturates there; under saturation each caller burns its full 15 s budget and returns `cause=timeout`: content passed unscanned, on every tool call, silently. Thread width cannot close the ML gap.

Only cheaper scans move the ML number. That is PET-178 (split the budget by layer) and PET-180 (source-trust tiers). Until per-scan cost drops, the inversion buys observability rather than coverage on ML deployments.

## Scope (verified against current files, 2026-09-16)

| Path | Current | Change |
|---|---|---|
| `petasos/session/guard.py` | `ingests` defaults False (`:8-9`, `:62-64`). `INGESTION_TOOLS` is the `ingests=True AND reaches_hook=True` inclusion derivation (`:407-408`). Unknown names are not in `_TOOL_AXES` and are unscanned. No `NON_INGESTING_TOOLS`. Vintage `_TOOL_AXES_VERIFIED_AGAINST` is `hermes-agent b415029b6 (2026-08-06)` (`:401`) | Flip default `ingests=True`. Publish `NON_INGESTING_TOOLS` from `ingests=False` rows. Keep `INGESTION_TOOLS` as the derived scan-selected export; it is no longer the gate. Exclusion rows with per-row evidence: `write_file`, `kanban_create`, `kanban_comment`, `patch`. `execute_code` and `terminal` stay default-ingest. `video_analyze` / `skill_view` / `skills_list` are not excluded |
| `docs/deployment/reference_plugin/__init__.py` | `_is_ingestion` is `canon in _INGESTION_CANON` (`:323-324`). Gate 3 skips unknowns and logs `PETASOS_INGEST_NOT_CLASSIFIED` (`:2194-2202`). `_is_ingestion("")` is False. `_derive_session_id` uses `task_id`, then `_agent`, else `anon-{uuid}` — no host `session_id` kwarg (`:936-951`). `ingest_unscanned` WARNING + event on every timeout/raised/boundary/floor_error (`:2284-2304`). Gate 4 returns None when not `_initialized` (`:2206-2207`) | `_is_ingestion` is `canon not in` exclusion canon, with a named-tool floor: blank/missing `tool_name` still skips. Unknown non-empty names scan. First-sighting DEBUG `PETASOS_INGEST_EXCLUDED` once per excluded canon (same latch as `_note_ingest_skip`, not an event). Bound `ingest_unscanned` log+event on a PET-131 cadence; never suppress the banner. Key: host `session_id` if present, else today's derived id, else one process-global uncorrelated bucket. Leave gate 4 alone |
| `tests/test_tool_axes.py` | `test_unknown_tool_defaults_stated_per_axis` (`:97-102`) pins unknown gated on arguments and **not** in `INGESTION_TOOLS`; docstring names PET-181 | Invert the result-axis half: unknown non-empty name is not in `NON_INGESTING_TOOLS`. Pin exclusion members. Pin empty name is not scanned. Argument-axis half unchanged |
| `tests/test_reference_plugin_tool_result.py` | Gate 3 keys `_is_ingestion` / `INGESTION_TOOLS` (filemap: 43 tests). Unknown names skip with `PETASOS_INGEST_NOT_CLASSIFIED` | An unregistered tool name and an unknown MCP wire name both have string results scanned (finding / banner / `ingest_flagged` as today's HIGH+ path). Excluded tools return None and emit `PETASOS_INGEST_EXCLUDED` once. `test_read_only_tool_still_never_blocked_for_its_arguments` stays unedited |
| `CHANGELOG.md` | Unreleased Changed records PET-179's two-axis derivation and `INGESTION_TOOLS` | Own Changed (or Fixed) line: unknown tools are result-scanned; exclusion set named; ML posture is observability plus a base-install floor until PET-178. Not a bullet inside the PET-179 entry |
| `docs/deployment/hermes-desktop.md` | `:222` distinguishes argument axis (`READ_ONLY_TOOLS`) from result scanning (`INGESTION_TOOLS`) | Document the inverted default, `NON_INGESTING_TOOLS`, and that `INGESTION_TOOLS` is no longer the seam's gate |

## Decisions carried forward

1. **Invert-only this ticket (Q1 C).** Unknown non-empty tools are scanned. No new pool, shed path, or new-population HIGH+ calibration. Until PET-178, ML is observability plus a base-install floor — why: four review rounds of the wide-scope spec died on the pool, and PET-179 already fenced concurrency to PET-178.
2. **Flip the table default and gate on exclusion (Q2 A).** Default `ingests=True`. Publish `NON_INGESTING_TOOLS`. `_is_ingestion` is `canon not in` exclusion. Keep `INGESTION_TOOLS` as a derived export, not the gate — why: an inclusion frozenset cannot name tools that are not in the table, which is the whole point of invert.
3. **Exclusion rule is evidence of no externally-authored content (Q3 A).** Rows: `write_file`, `kanban_create`, `kanban_comment`. `execute_code` and `terminal` stay scanned (stdout / process output is attacker-reachable; `MAX_STDOUT_BYTES = 50_000`, `docker_network` defaults True) — why: the ticket's criterion, confirmed against hermes-agent `b415029b6`.
4. **PET-179 carry-ins are not excluded (Q4 A).** `video_analyze`, `skill_view`, `skills_list` scan when the result is a string. Non-string still hits gate 2 — why: skill markdown is user- and project-authored; that is ingested content.
5. **Exclude `patch` (Q5 A).** The result is the agent's own difflib, not externally authored — why: scanning it flags Petasos's own rule source when editing `minimal.py`.
6. **Bound `ingest_unscanned` in this ticket (Q6 A, Q9 A).** PET-131-style per-session cadence; log and event share one clock; never suppress the banner. Key: host `session_id` if present, else `task_id`/`_agent` derived, else one process-global uncorrelated bucket — why: invert multiplies timeout volume, and today's anon-uuid-per-call key makes any per-session cap a no-op.
7. **Blank or missing `tool_name` is not scanned (Q8 A).** Unknown non-empty names are — why: an unnamed host call is not a registered Hermes or MCP tool.
8. **First-sighting DEBUG `PETASOS_INGEST_EXCLUDED` (Q10 A).** Once per canon, same latch as `PETASOS_INGEST_NOT_CLASSIFIED`. Not an event — why: the exclusion set must be falsifiable in a live deploy, and the old token would read as "we did not know this tool".
9. **Scale is a factor (Q7 A).** Target: ~68 of 72 Hermes tools plus unbounded MCP names. Dimensions: 8-wide `search_files` batch; base-install vs ML. Gateway P=80 saturation is a PET-178 residual, not this N.

## Done when

- An unregistered tool name and an unknown MCP tool both have their results scanned, pinned by a test.
- The concurrency posture is measured at a stated P, not asserted: added latency per tool call, shed rate per install shape, and the capacity line K/S for each.
- A wedged or saturated ingestion path cannot open the parameter-side fence, cannot stall subsequent dispatch unboundedly, and cannot observe a half-applied reconfigure.
- The ML posture is stated as what it is, observability plus a base-install floor, rather than as coverage, until PET-178 lands.
- PET-179's invariant holds: genuinely read-only tools are still never blocked for their arguments.

## Out of scope

- PET-178 cheaper / layered scans, admission pool, shed path, and the P=80 saturation fix (Q1 C).
- New-population HIGH+ recalibration; the PET-170 HIGH+ gate stays (Q1 C).
- Cold-start / failed-init result scanning; gate 4 of `transform_tool_result` stays (Q11 A).
- Config-supplied ingestion list (PET-125: an agent-reachable toggle is a self-disarm primitive).
- Argument-axis invert (`acts` stays fail-secure on unknown names).
- Gate 2 non-string widening (`vision_analyze` / `browser_vision` dict skip; PET-178).
- Reconfigure-vs-in-flight exclusion discipline and executor-shape (K threads vs K tasks) — those were ticket items 3–4 of the pool, fenced with it.

## Scale

**Factor:** yes
**Target:** ~68 of 72 Hermes tools plus unbounded MCP names
**Dimensions:** 8-wide `search_files` batch (`_PARALLEL_SAFE_TOOLS`); base-install syntactic cost vs ML cost. Gateway offered load P=80 is a PET-178 residual, not this target.

## Risks / decisions

1. `write_file` success JSON includes optional lint/LSP text, not only `bytes_written` (`hermes-agent-PET-158/tools/file_tools.py:1601-1608`) — operator claims "exclude write_file as no externally-authored content", unverified against the lint/LSP arm; spec author pins this.
2. `ingest_unscanned` cadence seconds (reuse `_DISARM_LOG_EVERY_S` or a sibling) — spec author pins this.
3. `verify.py` currently FAILs on a missing `INGESTION_TOOLS` export (`docs/deployment/reference_plugin/verify.py:203-214`); after that export is not the gate, whether to keep that row and/or require `NON_INGESTING_TOOLS` — spec author pins this.
4. Census N (~68/72 in the ticket vs PET-179's 81-tool census at `b415029b6`) — spec author pins this.

## References

- `petasos/session/guard.py:8-9` — unknown names default to not ingesting; PET-181 owns the invert.
- `petasos/session/guard.py:62-64` — row defaults `acts=True`, `ingests=False`, `reaches_hook=True`.
- `petasos/session/guard.py:407-408` — `INGESTION_TOOLS` inclusion derivation.
- `tests/test_tool_axes.py:97-102` — unknown gated on arguments, not in `INGESTION_TOOLS`.
- `docs/deployment/reference_plugin/__init__.py:323-324` — `_is_ingestion` inclusion membership.
- `docs/deployment/reference_plugin/__init__.py:405-451` — one `petasos-async` loop; `_run_async` is `run_coroutine_threadsafe` with no worker cap.
- `docs/deployment/reference_plugin/__init__.py:936-951` — `_derive_session_id`: `task_id`, `_agent`, else `anon-{uuid}`; no host `session_id` kwarg.
- `docs/deployment/reference_plugin/__init__.py:1190-1200` — `_note_ingest_skip` first-sighting DEBUG per `(canon, kind)`.
- `docs/deployment/reference_plugin/__init__.py:1203-1214` — PET-131 D1/D4: `_log_disarmed_bypass` returns whether it logged.
- `docs/deployment/reference_plugin/__init__.py:2194-2202` — gate 3 skips unknowns; `PETASOS_INGEST_NOT_CLASSIFIED`.
- `docs/deployment/reference_plugin/__init__.py:2206-2207` — gate 4: no scan when not `_initialized`.
- `docs/deployment/reference_plugin/__init__.py:2284-2304` — unbounded `ingest_unscanned` WARNING + event.
- `docs/specs/DONE/PET-179/superseded-wide-scope/` — parked v4 spec and four review rounds (ticket path `docs/specs/TODO/PET-179.superseded-wide-scope/` is stale).
- `hermes-agent-PET-158/tools/file_tools.py:1601-1608` — `write_file` success is `WriteResult` JSON, not file contents.
- `hermes-agent-PET-158/tools/file_operations.py:1083-1092` — `patch` success includes a unified diff.
- `hermes-agent-PET-158/tools/kanban_tools.py:402-403`, `:961-962` — `kanban_comment` / `kanban_create` return `_ok(...)` metadata.
- `hermes-agent-PET-158/tools/code_execution_tool.py:24-25`, `:75`, `:779` — `execute_code` stdout cap 50_000; `docker_network` defaults True.
- `hermes-agent-PET-158/tools/terminal_tool.py:2858-2860` — `terminal` returns process `"output"`.
- Wiki: `decisions/2026-09-15-pet-179-two-axis-tool-classification.md` Decision 2 (invert sequenced after PET-178).
- Wiki: `decisions/2026-08-06-pet-170-annotate-never-withhold.md` (HIGH+ on 816 read-shaped files; annotate never withhold).
- Wiki: `decisions/2026-06-15-pet-125-self-disarm-boundary-console-token.md` (no agent-reachable ingestion list).
- Plane: PET-178 Backlog (`4564b436-896f-4190-a38c-7126cb4717f2`).
- Interview: 3 rounds, exit empty-frontier (tree fully visited).
