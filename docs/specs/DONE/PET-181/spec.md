# PET-181 — Invert the ingestion-axis default: scan unknown tools by default

Brief: `docs/specs/TODO/PET-181.brief.md`
Plane: PET-181 (`082ef382-60ea-4027-a3a6-6eda00e243ef`, Backlog, high) — namespace `petasos`
Base: `9c4f2b9` (origin/master tip at preflight; PET-179 `0ee58ab` is the classification split this inverts)
Vintage of per-row evidence: `_TOOL_AXES_VERIFIED_AGAINST = "hermes-agent b415029b6 (2026-08-06)"` (`petasos/session/guard.py:401`), checked against the local `hermes-agent-PET-158` tree.

The Plane ticket still carries the 2026-08-06 wide-scope wording (pool, shed, HIGH+ recalibration). The brief is the local source of truth: invert-only, after four grilling rounds. This spec implements the brief.

## Goal

Close the result-axis fail-open that PET-179 left named. After PET-179, an unrecognised tool name is gated on arguments and **not scanned** on results. MCP servers register tools at runtime from per-deployment manifests, so that inclusion set cannot be made correct by enumeration. This ticket flips the table default to `ingests=True`, publishes `NON_INGESTING_TOOLS` from `ingests=False` rows, and gates `transform_tool_result` on exclusion plus a named-tool floor (blank/missing `tool_name` still skips). Unknown non-empty names — a tool Hermes adds next release, or an MCP server registers at runtime — are result-scanned without a Petasos change.

Until PET-178 drops per-scan cost, the inversion is **observability plus a base-install floor**, not ML coverage. No admission pool, no shed path, no new-population HIGH+ recalibration ships here. `ingest_unscanned` log+event is bound to a PET-131-style per-session cadence; the banner is never suppressed.

## Scope

### Files to change

| File | Change |
|---|---|
| `petasos/session/guard.py` | Flip `ToolAxes` default `ingests=True`. Add four exclusion rows (`write_file`, `kanban_create`, `kanban_comment`, `patch`) with structured evidence anchors. Publish `NON_INGESTING_TOOLS = _derive(_TOOL_AXES, ingests=False)`. Keep `INGESTION_TOOLS` as the named `ingests=True AND reaches_hook=True` derivation; it is no longer the seam's gate. Rewrite the module docstring so unknown names default to ingesting. Keep every currently-named ingesting row (do not drop the browser family). |
| `docs/deployment/reference_plugin/__init__.py` | Import `NON_INGESTING_TOOLS`. Build `_NON_INGESTING_CANON`. `_is_ingestion` is non-empty canon and `canon not in` exclusion. Gate 3: excluded canons emit first-sighting DEBUG `PETASOS_INGEST_EXCLUDED` via `_note_ingest_skip`; blank/missing skips with no `PETASOS_INGEST_NOT_CLASSIFIED`. Bound `ingest_unscanned` WARNING+event on a sibling of `_DISARM_LOG_EVERY_S`; never suppress the banner. Cadence key: host `session_id` if present, else `task_id` / `_agent` derived, else one process-global uncorrelated bucket. Leave gate 4 alone. Keep `_INGESTION_CANON` as the named-subset cache and `test_no_row_canonicalizes_away` pin only (cotenant overlap is Decision 11; rewrite the `PETASOS_INGESTION_SCAN_COTENANT` comment). |
| `docs/deployment/reference_plugin/verify.py` | `check_guard_exports` requires **both** `INGESTION_TOOLS` and `NON_INGESTING_TOOLS`; FAIL names the missing export(s). |
| `tests/test_tool_axes.py` | Invert the result-axis half of `test_unknown_tool_defaults_stated_per_axis`. Pin `NON_INGESTING_TOOLS` members and count. Empty name is not in the exclusion set and is not a table row. Argument-axis half unchanged. Update published counts (33 → 37 rows; `ingests=True` stays 29; `NON_INGESTING_TOOLS` is 8). |
| `tests/test_reference_plugin_tool_result.py` | Unregistered name and unknown MCP wire name both scan (finding / banner / `ingest_flagged` through a real `MinimalScanner`, copying `test_browser_navigate_poisoned_page_is_flagged`). Excluded tools return None and emit `PETASOS_INGEST_EXCLUDED` once. Blank `tool_name` still skips. Retarget `test_dangerous_and_unnamed_tools_are_not_scanned`, `test_non_canonicalizing_variants_go_unscanned_pinned_gap`, `test_ingest_not_classified_emits_once`, `test_monkeypatching_the_canon_set_moves_the_scanned_set`. `test_read_only_tool_still_never_blocked_for_its_arguments` stays unedited. Keep `test_every_ingestion_tool_is_scanned` as a named-subset pin. Update the security-guidance cotenant pin for `skill_manage` (D11). |
| `tests/test_verify.py` | Keep `test_missing_ingestion_tools_fails_main`. Add a sibling that `delattr`s `NON_INGESTING_TOOLS` and FAILs `main()`. Clean PASS text names both exports. |
| `tests/test_benchmarks.py` | Keep `write_file` as the excluded skip-path case. Add a measure-only unknown-tool cap-window case. Keep the 8-wide concurrent `inspect()` anchor. Document K=1 / no-shed in the new-case docstring. |
| `CHANGELOG.md` | Own Unreleased **Changed** (or **Fixed**) line, not a bullet inside the PET-179 entry: unknown tools are result-scanned; exclusion set named; `INGESTION_TOOLS` remains the named hook-reaching subset and is no longer the seam's gate (`NON_INGESTING_TOOLS` is); ML posture is observability plus a base-install floor until PET-178. Own **Added** line for `NON_INGESTING_TOOLS` (not re-exported from `petasos`, matching `READ_ONLY_TOOLS` / `INGESTION_TOOLS`). Amend the still-Unreleased PET-179 Added bullet in the same release so it does not publish "selection set" as current meaning (one clause: "PET-181: no longer the seam's membership test"). |
| `docs/deployment/hermes-desktop.md` | Document the inverted default, `NON_INGESTING_TOOLS`, and that `INGESTION_TOOLS` is no longer the seam's gate. |

### Files to leave alone

- Argument-axis code: `_is_dangerous`, `READ_ONLY_TOOLS`, `acts` default (`True`).
- Gate 2 non-string widening (`vision_analyze` / `browser_vision` dict skip) — PET-178.
- Gate 4 (`if not _initialized: return None`) and the "no `_maybe_reconfigure` on this hook" rule.
- `_derive_session_id` (PET-176 D6 correlator; cadence uses a separate helper).
- `_log_disarmed_bypass` and the PET-131 disarm clock.
- PET-170 HIGH+ ordinal gate, banner format, `_clip_result` window, `_result_scan_timeout`.
- `petasos/config.py` — no agent-reachable ingestion list (PET-125).
- CLAUDE.md ingestion-budget bullet — invert widens population, not per-scan cost; PET-178 owns the shared breaker.

## Decisions

### Decision 1 — Invert-only this ticket (brief Q1 C)

**Chosen.** Unknown non-empty tools are scanned. No new pool, shed path, or new-population HIGH+ calibration. Until PET-178, ML is observability plus a base-install floor.

**Rejected.** The Plane ticket's items 3–5 (bounded pool at P=8×loops, shed-path adversarial exposure, HIGH+ recalibration against the widened surface). Four review rounds of the wide-scope spec died on the pool; PET-179 already fenced concurrency to PET-178.

**Honors.** Brief Decision 1; wiki `decisions/2026-09-15-pet-179-two-axis-tool-classification.md` Decision 2 (invert sequenced after PET-178) and Decision 3 (no concurrency machinery in PET-179).

### Decision 2 — Flip the table default and gate on exclusion (brief Q2 A)

**Chosen.** Default `ingests=True`. Publish `NON_INGESTING_TOOLS`. Plugin `_is_ingestion` is:

```python
def _is_ingestion(tool_name: str) -> bool:
    canon = canonicalize_tool_name(tool_name)
    if not canon:
        return False  # named-tool floor; blank/missing/whitespace-only
    return canon not in _NON_INGESTING_CANON
```

Keep `INGESTION_TOOLS = _derive(_TOOL_AXES, ingests=True, reaches_hook=True)` as a derived export. It names the classified, hook-reaching subset; it cannot name tools that are not in the table, which is the point of invert, so it is no longer the gate.

**Rejected.** Keep an inclusion frozenset as the gate. An inclusion set cannot name a runtime MCP tool.

**Row hygiene.** A row still exists where a tool **deviates** from the new defaults (`acts=True`, `ingests=True`, `reaches_hook=True`) **or** already carries a per-row evidence pin. Do **not** drop the twelve `browser_*` rows that now match the default: PET-179 rejected silent membership drops on a published set (wiki Decision 4, the `mcp_*` seats). Dropping them would shrink `INGESTION_TOOLS` from 17 to 5 with no behavior change. Keep them as evidence pins.

**`reaches_hook` is not part of the gate.** After invert, `_is_ingestion` does not AND `reaches_hook`. Tools with `ingests=True` and `reaches_hook=False` (`session_search`, `read_terminal`, ten `mcp_*` dead names) scan **if they actually reach the hook**. The flag remains the `INGESTION_TOOLS` filter only.

### Decision 3 — Exclusion rule is evidence of no externally-authored content (brief Q3 A, Q4 A, Q5 A)

**Chosen.** New `ingests=False` rows (all `acts=True`, `reaches_hook=True`, matching today's implicit default on those axes):

| Name | Evidence anchor | Why excluded |
|---|---|---|
| `write_file` | `hermes tools/file_tools.py::_handle_write_file` | Success is `WriteResult` JSON (`bytes_written`, `dirs_created`, optional `lint` / `lsp_diagnostics`). Not file contents. |
| `kanban_create` | `hermes tools/kanban_tools.py::_handle_create` | `_ok(task_id, status, workspace_kind, workspace_path, project_id, subscribed)` — metadata, not task body. |
| `kanban_comment` | `hermes tools/kanban_tools.py::_handle_comment` | `_ok(task_id, comment_id)` — metadata, not comment body. |
| `patch` | `hermes tools/file_tools.py::_handle_patch` | Result is the agent's own `difflib.unified_diff`. Scanning it flags Petasos's own rule source when editing `minimal.py`. |

`execute_code` and `terminal` stay default-ingest: stdout / process output is attacker-reachable (`MAX_STDOUT_BYTES = 50_000`; `docker_network` defaults True; `terminal` returns process `"output"`).

PET-179 carry-ins are not excluded: `video_analyze`, `skill_view`, `skills_list` scan when the result is a string. Non-string still hits gate 2.

**Existing `ingests=False` rows stay.** `todo`, `memory`, `clarify`, `delegate_task` already deviate (`ingests=False`, `reaches_hook=False`). They become members of `NON_INGESTING_TOOLS` without a policy change. This ticket does not start scanning them.

**`NON_INGESTING_TOOLS` membership (8):** `clarify`, `delegate_task`, `kanban_comment`, `kanban_create`, `memory`, `patch`, `todo`, `write_file`.

### Decision 4 — `write_file` lint/LSP residual (brief risk 1)

**Chosen.** Exclude `write_file` anyway. `WriteResult.to_dict` includes optional `lint` and `lsp_diagnostics` when the success path set them (`hermes-agent-PET-158/tools/file_operations.py:177-193`, `:1557-1562`; returned via `file_tools.py:1601-1608`). That text is process-local diagnostic output of the agent's own write, not third-party ingested content (MCP / web / file / browser). The same residual applies to `patch`, which also carries optional lint/LSP beside the diff.

**Residual, recorded not scanned:** a hostile local LSP plugin that injected into diagnostics would be unscanned. That is not this ticket's threat model. Do not add a lint-shaped scan of those JSON fields.

### Decision 5 — Bound `ingest_unscanned` (brief Q6 A, Q9 A; risk 2)

**Chosen.** PET-131 D1/D4 shape: log and event share one clock (the helper returns whether it logged; the caller emits the event iff True). Never suppress the banner (`format_result_notice("scan_unavailable", ...)` still concatenates on every timeout/raised/boundary/floor_error/`no_pipeline`).

**Window.** Sibling constant `_INGEST_UNSCANNED_LOG_EVERY_S = _DISARM_LOG_EVERY_S` (30.0). Own lock and own `{key: monotonic}` map, matching how `_last_attribution_log` / `_last_reload_fail_log` reuse the window without sharing the disarm clock. A shared clock would let a burst of timeouts suppress `PETASOS_DISARMED`.

**Key, in this order:**

1. Host `kwargs["session_id"]` if it is a non-empty `str`. Hermes already passes `session_id=` (`hermes-agent-PET-158/model_tools.py:1392-1406`).
2. Else `task_id` if truthy.
3. Else, if `kwargs["_agent"]` is not None, the stable `desktop-{uuid12}` from the existing `_session_ids` map (same lookup `_derive_session_id` uses; do not mint a second id).
4. Else the one process-global bucket `"uncorrelated"`. **Do not** fall through to `anon-{uuid8}`: that is today's per-call mint, which would make any per-session cap a no-op.

**Do not mutate `_derive_session_id`.** PET-176 D6 still treats empty `task_id` and no `_agent` as uncorrelatable for frequency. Cadence is a separate helper `_ingest_unscanned_cadence_key`. The `ingest_unscanned` event's `session_id` field stays `_derive_session_id(...)` so the correlator contract does not silently start accumulating under host `session_id`.

**Map bound.** Drop-oldest at `_MAX_DISARM_SESSIONS` (10_000). First-sighting skip keys stay capped at 512; this clock is per session, not per (canon, kind).

**Test seam.** `_reset_ingest_unscanned_log` clears the cadence map, sibling of `_reset_ingest_log`.

### Decision 6 — Blank or missing `tool_name` is not scanned (brief Q8 A)

**Chosen.** Unknown **non-empty** names scan. An unnamed host call is not a registered Hermes or MCP tool. The floor is after `canonicalize_tool_name`, so whitespace-only that strips to `""` also skips (`normalize.py:220-227`).

**Token.** Retire `PETASOS_INGEST_NOT_CLASSIFIED`. Blank skip is silent (no new `PETASOS_INGEST_UNNAMED` token). The named-tool floor is pinned by test, not by a live-deploy tripwire. Exclusion uses `PETASOS_INGEST_EXCLUDED`.

### Decision 7 — First-sighting DEBUG `PETASOS_INGEST_EXCLUDED` (brief Q10 A)

**Chosen.** Once per excluded canon, same latch as today's `_note_ingest_skip` (`(canon[:64], kind)` with `kind="excluded"`). DEBUG, not an event. The exclusion set must be falsifiable in a live deploy, and `PETASOS_INGEST_NOT_CLASSIFIED` would read as "we did not know this tool".

`PETASOS_INGEST_NOT_STRING` (gate 2) is unchanged. After invert it fires for any ingesting name whose result is non-string, including newly scanned unknowns — that is correct.

### Decision 8 — Scale is a factor (brief Q7 A / `## Scale`)

**Factor:** yes.

**Target N:** every non-empty tool name that reaches `transform_tool_result` except the eight-member exclusion set, plus unbounded MCP wire names.

**Census pin (brief risk 4).** The ticket's ~68/72 is 2026-08-06 split-day arithmetic (hermes-desktop.md's "70+", four ingesting tools then). The PET-179 / plugin-comment census is **81** production `registry.register(...)` names (`HANDOFF-2026-08-06.md`; `_MAX_INGEST_LOG_KEYS` comment at `reference_plugin/__init__.py:193`). Named-table N after this ticket: **37** rows (33 + 4 exclusions). `INGESTION_TOOLS` stays **17** (named, hook-reaching; not the gate). `NON_INGESTING_TOOLS` is **8**. Conceptual registered-tool ingesting fraction is 81 − 8 = **73 of 81**, plus unbounded MCP names. Tools with `reaches_hook=False` may never present at the seam; that does not shrink the policy N.

**Dimensions.** 8-wide `search_files` batch (`_PARALLEL_SAFE_TOOLS`); base-install syntactic cost vs ML cost. Gateway offered load P=80 (10 concurrent turns × 8 tool workers; P=320 with default subagents) is a **PET-178 residual**, not this target. This ticket's measured P is **P=8** on the existing single `petasos-async` loop (K=1).

**Capacity line, stated not implemented.** K = 1 (one `petasos-async` loop, `_run_async` is `run_coroutine_threadsafe` with no worker cap). S = measured serial cap-window scan (existing `test_benchmark_ingestion_result_8kb`, ~7.3 ms normalized base-install). Capacity = 1/S. Shed rate = **0 by construction** (no shed path). Under saturation the existing behavior remains: each caller burns `_result_scan_timeout` and returns `cause=timeout` (banner + passthrough + cadence-bounded `ingest_unscanned`). Thread width cannot close the ML gap; PET-178 owns cheaper scans.

### Decision 9 — Done-when 2 and 3 map to measurement and residuals, not a pool

The brief's acceptance bullets 2 and 3 still use pool-era language ("shed rate", "cannot observe a half-applied reconfigure"). Decision 1 forbids implementing that machinery. Mapping:

| Bullet | What this ticket actually ships |
|---|---|
| Measured at a stated P; added latency; shed rate; K/S | Measure-only benchmarks at **P=8** (existing 8-wide + new unknown-tool 8 KB case). Shed rate recorded as 0. K/S recorded as 1/S in the benchmark docstring and CHANGELOG. P=80 is named as PET-178 residual, not re-derived. |
| Wedged/saturated path cannot open the parameter-side fence | Invert adds **no** lock acquisition on the shared loop. `_pre_tool_call` is unchanged. `test_read_only_tool_still_never_blocked_for_its_arguments` stays unedited. |
| Cannot stall subsequent dispatch unboundedly | Invert adds **no** queue. Each wait is still `_result_scan_timeout`. Residual: under saturation every caller burns the full timeout — PET-178. |
| Cannot observe a half-applied reconfigure | Invert adds **no** reconfigure site. `_maybe_reconfigure` still runs only on `_pre_tool_call`. Residual owned by PET-178. |

### Decision 10 — `verify.py` keeps `INGESTION_TOOLS` and requires `NON_INGESTING_TOOLS` (brief risk 3)

**Chosen.** `check_guard_exports` imports both names, FAILs listing whichever is missing, PASSes naming both. An old library missing `INGESTION_TOOLS` is still skew (PET-179 floor). A library that has `INGESTION_TOOLS` but predates this ticket is the new skew.

Plugin module docstring (`__init__.py:14-29`) adds `NON_INGESTING_TOOLS` to the listed floor next to `INGESTION_TOOLS`.

### Decision 11 — `skill_manage` cotenant overlap is accepted

Hermes bundles `plugins/security-guidance`, which registers `transform_tool_result` for `{write_file, patch, skill_manage}`. Today `test_bundled_security_guidance_target_set_can_never_contend` pins that set disjoint from `_INGESTION_CANON`. After invert, `write_file` and `patch` stay excluded (still disjoint). `skill_manage` has no table row, so it inherits ingest and **overlaps**.

**Chosen.** Do not add `skill_manage` to the exclusion set (brief did not name it; Q3 requires evidence of no externally-authored content, which this ticket did not gather). Update the test: `write_file` and `patch` remain disjoint from the **scanned** set (not in `_NON_INGESTING_CANON` inverted... they **are** in the exclusion set, so they are not scanned). Pin `skill_manage not in NON_INGESTING_TOOLS` and document the host first-string-wins residual (pre-existing PET-170 contract). The cotenant INFO log stays.

## Design

### Table (`petasos/session/guard.py`)

1. Rewrite the whole `ToolAxes` docstring, not only the three default bits: defaults are `acts=True`, `ingests=True`, `reaches_hook=True`; a row exists where a tool **deviates** from those defaults **or** already carries a per-row evidence pin (the PET-179 browser family, which now matches the default and must not be dropped).
2. Module docstring: unknown names default to ingesting (fail toward scrutiny). `INGESTION_TOOLS` is the named subset the seam *used to* select; the seam now selects by exclusion. PET-181 closed the fail-open.
3. Append the four exclusion rows to `_TOOL_AXES_ROWS` with the evidence strings in Decision 3. Do not reorder existing rows.
4. After `INGESTION_TOOLS`:

```python
NON_INGESTING_TOOLS: frozenset[str] = _derive(_TOOL_AXES, ingests=False)
```

5. Comment on `INGESTION_TOOLS` no longer says "Unknown names are unscanned (fail-open; PET-181)". Replace with: named hook-reaching ingesting tools; the seam gates on `NON_INGESTING_TOOLS`.

`READ_ONLY_TOOLS` and `_derive` are unchanged. `test_derive_is_the_only_source` gains `assert _derive(_TOOL_AXES, ingests=False) == NON_INGESTING_TOOLS`.

### Plugin gate 3

Keep gate order: disarm → shape → ingestion predicate → `_initialized`.

Replace the gate-3 block (`__init__.py:2184-2202`):

- If not `_is_ingestion(tool_name)`:
  - If canon is empty: `return None` (no log).
  - Else: `_note_ingest_skip(canon, "excluded", "PETASOS_INGEST_EXCLUDED tool=%s canon=%s", tool_name, canon)` then `return None`.

`PETASOS_INGEST_EXCLUDED` fires only for a non-empty string result of an excluded canon (gate 2 still runs first). Empty or non-string results of excluded tools stay silent at gate 2.

Build `_NON_INGESTING_CANON` beside `_INGESTION_CANON`. Keep the dropped-name WARNING for `INGESTION_TOOLS` as **named-subset hygiene only** (it is not a scan-skip). Add a sibling for exclusion names that canonicalize away: that residual is **scanned** (fail toward scrutiny), the opposite polarity of the old inclusion empty-drop comment at `__init__.py:308-311`. Pin both with `test_no_row_canonicalizes_away` extended.

`_INGESTION_CANON` remains, still built from `INGESTION_TOOLS`, for the named-subset pin. It is not consulted by `_is_ingestion`.

At the `PETASOS_INGESTION_SCAN_COTENANT` site (`__init__.py:2546-2552`): keep emitting the INFO token; rewrite the comment and message so they no longer claim the bundled `security-guidance` target set "can never contend". `write_file` / `patch` stay excluded; `skill_manage` inherits ingest and can contend under host first-string-wins (PET-170). Update `_MAX_INGEST_LOG_KEYS` comment: 512 still bounds memory for unbounded MCP not-string first-sighting; drop-oldest duplicates DEBUG rather than suppressing it; the eight exclusion latches cannot fill the cap. Do not split the map in this ticket.

### `ingest_unscanned` cadence

Replace the unconditional `logger.warning` + `_emit_enforcement_event` pair at `__init__.py:2284-2303` with an inner `try` so a cadence-helper exception cannot take the banner (outer fail-open would `return None`). The `format_result_notice(...) + result` return always runs:

```python
try:
    logged = _log_ingest_unscanned(tool_name, session_id, cause, len(result), task_id, kwargs)
    if logged:
        _emit_enforcement_event(
            session_id=session_id,
            tool=tool_name,
            event_type="ingest_unscanned",
            reason=f"{_RESULT_SCAN_ERROR_REASON} cause={cause} len={len(result)}",
        )
except Exception:
    logger.warning("PETASOS_INGEST_UNSCANNED_CADENCE_ERROR tool=%s cause=%s", tool_name, cause)
return format_result_notice("scan_unavailable", tool_name) + "\n\n" + result
```

`_log_ingest_unscanned` emits `PETASOS_INGEST_UNSCANNED tool=%s session=%s cause=%s len=%d` at WARNING. `session=` is the **derived** id already computed for this call (`_derive_session_id(...)`), not the cadence key. The helper returns whether it logged.

Cadence-key type guard, every step: `isinstance(value, str) and value.strip()` (Hermes production is `session_id=session_id or ""` — key present, empty string — treat as fall-through, identical to omitted). A truthy non-str must not be used as a dict key.

When `_agent is not None`, use the already-derived `session_id` argument (it is the `desktop-{uuid12}`). Do not re-read `_session_ids`. Do not call `_derive_session_id` from the cadence helper.

Existing cause tests fire one event each and stay green. Add a two-call-within-window test: second call still returns the banner, emits no second WARNING and no second event; the WARNING that did fire greps `PETASOS_INGEST_UNSCANNED` and the derived session id. Add a host-`session_id` test: two different `task_id`s sharing one non-empty `session_id=` share the clock; two `session_id`s do not; both `inspect` calls still receive `session_id=None` / `weight_cap=0.0` when `task_id` is empty and `_agent` is None. Add an uncorrelated test: empty `task_id`, no `_agent`, `session_id=""` (Hermes shape) — two calls share the `"uncorrelated"` bucket. Add same-`_agent` / different-`_agent` pins. Add `session_id=None` and a non-str `session_id` as fall-through, banner still present.

### Canonicalizer-miss variants

`test_non_canonicalizing_variants_go_unscanned_pinned_gap` currently pins `readfile` / `Read__File` / `mcp__vigil_harbor__memory_search` as unscanned. After invert those non-empty names **scan**. Retarget the test to assert they scan (stub pipeline, one call). The argument-axis still fail-secures unknowns (unchanged). The recorded "fail DIRECTION inverts here" gap **closes on the result axis**; that is this ticket.

### Alias layer is not the exclusion layer

`DEFAULT_TOOL_ALIASES` maps `"write_file" → "write"` and `"terminal" → "exec"` on the **parameter** path. Ingestion uses `canonicalize_tool_name` only. A host that sends `write` scans it (not an exclusion member). Do not auto-exclude aliases. Hermes hands registered names.

Exclusion is on the canonical bare name (PET-118). An MCP wire name that strips onto an exclusion member (`mcp__acme__write_file` → `write_file`) is treated as that Hermes tool, not as "unknown MCP". Do not skip canonicalize to "fix" this. Pin `mcp__acme__write_file` and one other exclusion member as excluded-by-canonicalize. The unknown-MCP HIGH+ test must use a bare name that does **not** collide (`mcp__some_server__some_tool` → `some_tool`).

## Test plan

### `tests/test_tool_axes.py`

- `test_unknown_tool_defaults_stated_per_axis`: unknown not in `READ_ONLY_TOOLS` (argument fail-secure, unchanged); unknown **not** in `NON_INGESTING_TOOLS`; unknown not in `_TOOL_AXES`. Drop the "unscanned on results" reading of `not in INGESTION_TOOLS` as the gate pin — `not in INGESTION_TOOLS` remains true (named-set completeness) and is not the seam's decision.
- New: `test_exclusion_members_are_pinned` — `NON_INGESTING_TOOLS` equals the eight-name frozenset in Decision 3. Empty string not in it.
- New: `test_execute_code_and_terminal_are_not_excluded`; `video_analyze` / `skill_view` / `skills_list` not excluded.
- `test_published_counts`: `len(_TOOL_AXES) == 37`; `len(READ_ONLY_TOOLS) == 16`; `len(INGESTION_TOOLS) == 17`; `len(NON_INGESTING_TOOLS) == 8`; `sum(ingests) == 29`.
- `test_table_is_immutable_and_has_no_duplicate_keys` and `test_full_membership_is_pinned`: update the 33 literals; pin `tuple(sorted(NON_INGESTING_TOOLS))`.
- `test_every_row_carries_a_structured_evidence_anchor` covers the four new rows via `_EVIDENCE_RE`.
- `test_argument_axis_does_not_widen` unchanged.

### `tests/test_reference_plugin_tool_result.py`

- New: `test_unregistered_tool_poisoned_result_is_flagged` — tool name `definitely_not_a_registered_tool`, real `Pipeline` + `MinimalScanner`, same assertions as `test_browser_navigate_poisoned_page_is_flagged` (banner, content intact, `injection.ignore-previous`, `ingest_flagged`).
- New: `test_unknown_mcp_wire_name_poisoned_result_is_flagged` — `mcp__some_server__some_tool` (canonicalizes to a non-empty name not in the exclusion set). Same HIGH+ path.
- New: `test_excluded_tools_are_not_scanned` — parametrize the four new names; stub pipeline; `out is None`; `stub.calls == []`.
- New: `test_ingest_excluded_emits_once` — `write_file` twice; one DEBUG `PETASOS_INGEST_EXCLUDED`; replace `test_ingest_not_classified_emits_once`.
- New: `test_blank_tool_name_is_not_scanned` — `tool_name=""` and whitespace that canonicalizes to `""`, both with `result="content"` so gate 3's named-tool floor actually runs (an empty result would pass via gate 2). Assert `stub.calls == []`, no `PETASOS_INGEST_EXCLUDED`, no `PETASOS_INGEST_NOT_CLASSIFIED`. Optional second case with `result=""` shows gate 2 still wins.
- Split `test_dangerous_and_unnamed_tools_are_not_scanned`: `write_file` stays skip; `exec`, `terminal`, `send_email` become scan; `""` stays skip.
- Retarget `test_non_canonicalizing_variants_go_unscanned_pinned_gap` as above.
- Retarget `test_monkeypatching_the_canon_set_moves_the_scanned_set` onto `_NON_INGESTING_CANON` (empty exclusion scans `write_file`; adding `read_file` to exclusion skips it).
- Keep `test_every_ingestion_tool_is_scanned` (named subset still scans).
- Keep `test_read_only_tool_still_never_blocked_for_its_arguments` **byte-for-byte**.
- Retitle `test_bundled_security_guidance_target_set_can_never_contend` so it does not still claim "can never contend". Pin `write_file` / `patch` excluded (in `NON_INGESTING_TOOLS` / `_NON_INGESTING_CANON`); pin `skill_manage not in NON_INGESTING_TOOLS`.
- New: `test_mcp_wire_name_that_strips_onto_exclusion_is_excluded` — `mcp__acme__write_file` and one other exclusion member; stub pipeline; skip, one `PETASOS_INGEST_EXCLUDED`.
- New cadence tests per Decision 5 and the Design cadence block (window, host `session_id` including `""` / `None` / non-str, uncorrelated bucket, same-`_agent` / different-`_agent`). Banner always present on the second call. Host-`session_id` with empty `task_id` and no `_agent` still calls `inspect(..., session_id=None, weight_cap=0.0)`.

### `tests/test_verify.py`

- Keep `test_missing_ingestion_tools_fails_main`.
- Add `test_missing_non_ingesting_tools_fails_main` (same shape, `NON_INGESTING_TOOLS`).
- Assert clean PASS detail names both exports.

### `tests/test_benchmarks.py` (measure-only, existing `pytest_benchmark` skipif)

- Keep `test_benchmark_ingestion_non_ingestion_tool_large_result` on `write_file` (still the skip path). Update the docstring: excluded tool, not "dangerous tool".
- Add `test_benchmark_ingestion_unknown_tool_8kb` — same payload as the 8 KB `read_file` case, `tool_name="definitely_not_a_registered_tool"`. Docstring states K=1, shed rate 0, capacity 1/S, P=8 measured / P=80 residual.
- Keep `test_benchmark_ingestion_result_8wide_concurrent`.

### Regression

- Argument-axis unknown still gated (`test_unknown_tool_defaults_stated_per_axis` plus existing guard tests).
- PET-170 HIGH+ on `read_file` still annotates, never withholds.
- PET-179 browser family still scanned and still argument-gated.

## Test command

Local smoke, matching sibling PET specs on this machine:

```
C:\python310\python.exe -m pytest tests/test_tool_axes.py tests/test_reference_plugin_tool_result.py tests/test_verify.py tests/test_benchmarks.py -q
```

`tests/test_benchmarks.py` skipifs when `pytest_benchmark` is absent; the functional files are the gate. Full shipping suite before PR, as PET-179: `C:\python310\python.exe -m pytest` plus the six CI jobs.

Authoritative runtime is CI Python 3.11 / 3.12 / 3.13 (`requires-python = ">=3.11"`). The 3.10 local interpreter is the established smoke pin, not the support floor.

## Done when

Mapped 1:1 to the brief:

- An unregistered tool name and an unknown MCP tool both have their results scanned, pinned by a test. (`test_unregistered_tool_poisoned_result_is_flagged`, `test_unknown_mcp_wire_name_poisoned_result_is_flagged`)
- The concurrency posture is measured at a stated P, not asserted: added latency per tool call, shed rate per install shape, and the capacity line K/S for each. (P=8 measure-only benchmarks; shed rate 0; K=1; S from the 8 KB case; P=80 named as PET-178 residual — Decision 8 and 9)
- A wedged or saturated ingestion path cannot open the parameter-side fence, cannot stall subsequent dispatch unboundedly, and cannot observe a half-applied reconfigure. (Invert adds none of the machinery that could violate those; residuals stay PET-178 — Decision 9. Parameter-side pin: `test_read_only_tool_still_never_blocked_for_its_arguments` unedited.)
- The ML posture is stated as what it is, observability plus a base-install floor, rather than as coverage, until PET-178 lands. (CHANGELOG + hermes-desktop.md + this spec's Decision 1)
- PET-179's invariant holds: genuinely read-only tools are still never blocked for their arguments. (`test_read_only_tool_still_never_blocked_for_its_arguments`, `test_argument_axis_does_not_widen`, `test_browser_navigate_is_scanned_and_still_argument_gated`)

## Out of scope

Carried from the brief:

- PET-178 cheaper / layered scans, admission pool, shed path, and the P=80 saturation fix (Q1 C).
- New-population HIGH+ recalibration; the PET-170 HIGH+ gate stays (Q1 C).
- Cold-start / failed-init result scanning; gate 4 of `transform_tool_result` stays (Q11 A).
- Config-supplied ingestion list (PET-125: an agent-reachable toggle is a self-disarm primitive).
- Argument-axis invert (`acts` stays fail-secure on unknown names).
- Gate 2 non-string widening (`vision_analyze` / `browser_vision` dict skip; PET-178).
- Reconfigure-vs-in-flight exclusion discipline and executor-shape (K threads vs K tasks) — those were ticket items 3–4 of the pool, fenced with it.
- Mutating `_derive_session_id` or accumulating frequency under host `session_id`.
- Excluding `skill_manage` to restore a perfect cotenant disjoint set (Decision 11).
- Scanning `write_file` / `patch` lint/LSP JSON fields (Decision 4 residual).
- Dropping browser-family rows that now match the default (Decision 2).

## Post-green polish

Round 1 was green (P0=0 P1=0 across four lenses). Folded pre-ship P2 clarifications into Scope / Design / Test plan only; Decisions, Out of scope, and Done-when are untouched.

- correctness/R1/F-1, conventions/R1/F-3: `_INGESTION_CANON` is named-subset hygiene, not the cotenant pin; rewrite `PETASOS_INGESTION_SCAN_COTENANT` comment/message; exclusion empty-drop is scanned.
- correctness/R1/F-2: `_log_ingest_unscanned` WARNING token and `session=` is the derived id.
- correctness/R1/F-3, conventions/R1/F-4: `ToolAxes` docstring rewritten as deviate-or-evidence-pin, browser family named.
- conventions/R1/F-2: CHANGELOG states `INGESTION_TOOLS` is no longer the seam's gate; PET-179 Added bullet amended in the same release.
- edge-cases/R1/F-1: type-guard every cadence key; Hermes `session_id=""` falls through; inner try so the banner always returns.
- edge-cases/R1/F-2, conventions/R1/F-6: when `_agent` is present, use the already-derived `session_id`; do not re-read `_session_ids`.
- edge-cases/R1/F-3: host-`session_id` cadence test also pins `inspect(..., session_id=None)`.
- edge-cases/R1/F-4, correctness/R1/F-4: MCP strip onto an exclusion member is canonical identity, pinned.
- edge-cases/R1/F-5: blank-name test drives `result="content"`.
- edge-cases/R1/F-6: `PETASOS_INGEST_EXCLUDED` is string-result-only (Design note).
- edge-cases/R1/F-7: 512-cap comment re-justified; map not split.

## Deferred (P2+)

- conventions/R1/F-1 (P2, pre-ship): Decision 1's Honors line names wiki PET-179 sequencing ("invert after PET-178") while this ticket ships invert-only with PET-178 still Backlog. 2g cannot edit Decisions. Follow-up: replace that Honors clause with an explicit supersession of *sequencing only* (keep wiki Decisions 1 and 3).
- scalability/R1/F-1 (P2, pre-ship): split `kind="excluded"` off the 512 drop-oldest map so MCP not-string keys cannot evict exclusion latches. New mechanism; exceeds 2g. Design records "once" without that pin is until eviction.
- conventions/R1/F-5 (P3): drift-check list of spec-author pins; no edit required.
