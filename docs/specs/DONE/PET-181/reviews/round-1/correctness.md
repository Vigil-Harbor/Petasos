# Correctness Review — round 1

## Closure of round 0 findings
N/A — round 1

Deferred-findings: no `## Deferred — follow-up required` section. On round 1 with no deferrals that is not a routing violation.

Ticket PET-181 was retrieved from shared memory (`082ef382-60ea-4027-a3a6-6eda00e243ef`, Backlog, high). Its five Acceptance bullets match the brief. Ticket Scope still names the pool / shed path / HIGH+ recalibration; the brief and spec Decision 1 fence those to PET-178. Acceptance is mapped; that Scope remainder is not an unmapped Done-when.

Grounding that held: `ToolAxes` defaults and `INGESTION_TOOLS` derivation at `petasos/session/guard.py:8-9`, `:62-64`, `:407-408`; 33 rows, `ingests=True` count 29, `INGESTION_TOOLS` 17, `READ_ONLY_TOOLS` 16; `_is_ingestion` / gate 3 / `ingest_unscanned` / `_derive_session_id` / `_note_ingest_skip` / `_log_disarmed_bypass` / `_DISARM_LOG_EVERY_S = 30.0` line anchors in the plugin; Hermes `session_id=` at `model_tools.py:1398`; exclusion-row evidence (`_handle_write_file`, `_handle_patch`, kanban `_ok(...)`, `MAX_STDOUT_BYTES = 50_000`, terminal `"output"`); `canonicalize_tool_name` at `normalize.py:220-227`; `_NAMESPACE_PREFIX_RE` strips `mcp__<server>__`; `_plugin()` re-execs the module so existing one-event cause tests stay green under a per-session cadence map. Cited plugin/guard lines still match tip `9c4f2b9` (PET-179 `0ee58ab` is the classification split).

## Findings

### F-1: Cotenant INFO and `_INGESTION_CANON` comments still describe the inclusion gate
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:158-162 (Decision 11); spec.md:23 (Files to change, `_INGESTION_CANON` parenthetical); spec.md:191-193 (keep `_INGESTION_CANON` / dropped-name WARNING)
**Claim:** “The cotenant INFO log stays.” Files to change keeps `_INGESTION_CANON` as the “cotenant disjoint pin”. Design keeps the `INGESTION_TOOLS` dropped-name WARNING and adds an exclusion sibling.
**Why this is wrong:** After invert the seam no longer consults `_INGESTION_CANON`. Two live texts become false if left as-is:

1. `docs/deployment/reference_plugin/__init__.py:2546-2552` tells operators the bundled `security-guidance` target set “is disjoint from `_INGESTION_CANON`, so it can never contend”. Decision 11 itself makes `skill_manage` inherit ingest, so stock Hermes *can* contend (host first-string-wins). `write_file` / `patch` stay excluded; `skill_manage` does not. The test is updated; the INFO line is not.
2. `__init__.py:308-311` says a listed name that canonicalizes away is “never scanned (fail-open, silently)”. That polarity is the *inclusion* empty-drop. On `_NON_INGESTING_CANON` a dropped exclusion name is *scanned* (fail toward scrutiny). Copying the old comment onto the new WARNING would invert the residual.

`test_bundled_security_guidance_target_set_can_never_contend` currently asserts `security_guidance_targets & ref._INGESTION_CANON` (`tests/test_reference_plugin_tool_result.py:1279-1286`). That assertion still passes after invert (`skill_manage` is not in `INGESTION_TOOLS`) and would hide the overlap D11 is trying to document.
**Suggested fix:** Decision 11: keep emitting `PETASOS_INGESTION_SCAN_COTENANT`, rewrite the message to name first-string-wins and the `skill_manage` overlap; retarget the test onto the scanned set (`not in _NON_INGESTING_CANON`) plus `skill_manage not in NON_INGESTING_TOOLS`. Rewrite the `_INGESTION_CANON` empty-drop comment so it is named-subset hygiene only, and state that an exclusion name that canonicalizes away is scanned, not skipped.

### F-2: `_log_ingest_unscanned` does not pin the WARNING token or which session id it prints
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:195-211 (Design — `ingest_unscanned` cadence); spec.md:98-116 (Decision 5)
**Claim:** Replace the unconditional `logger.warning` + `_emit_enforcement_event` pair with `_log_ingest_unscanned(...)`; “PET-131 D1/D4 shape: log and event share one clock”; event `session_id` stays `_derive_session_id(...)`.
**Why this is wrong:** The helper body is not written. Today’s line is `PETASOS_INGEST_UNSCANNED tool=%s session=%s cause=%s len=%d` using the derived id (`__init__.py:2285-2290`). Decision 5 pins the *event* field and the *cadence key*, not the log line. An implementer who prints the cadence key would log `session=uncorrelated` (or the host `session_id`) while the event carries `anon-<uuid>` / `task_id`. No existing test greps that token (cause tests read the event spool). The new two-call test only says “no second WARNING”.
**Suggested fix:** Specify `_log_ingest_unscanned` emits `PETASOS_INGEST_UNSCANNED tool=%s session=%s cause=%s len=%d` at WARNING, `session=` is the derived id passed in (not the cadence key), and the helper returns whether it logged. Pin that in the two-call test.

### F-3: ToolAxes docstring “row exists only where it deviates” vs keeping default-matching browser rows
**Severity:** P2
**Where:** spec.md:69 (Decision 2 Row hygiene); spec.md:168 (Design Table item 1)
**Claim:** Design item 1: “`ToolAxes` docstring defaults become `acts=True`, `ingests=True`, `reaches_hook=True`.” Decision 2: do not drop the twelve `browser_*` rows that now match those defaults.
**Why this is wrong:** The current docstring is “A row exists only where a tool deviates from the defaults: `acts=True`, `ingests=False`, `reaches_hook=True`.” (`guard.py:63-64`). Updating only the three default bits leaves “only where a tool deviates” false for every `browser_*` row Decision 2 keeps as evidence pins. An implementer who treats that sentence as load-bearing could drop the twelve rows and shrink `INGESTION_TOOLS` from 17 to 5 — the silent membership drop wiki Decision 4 and spec Decision 2 forbid. Counts tests would catch it; the docstring instruction would not.
**Suggested fix:** Design item 1 must also rewrite the sentence: a row exists where a tool deviates from the new defaults *or* already carries a per-row evidence pin (the PET-179 browser family).

### F-4: MCP namespace strip can map an unknown wire name onto an exclusion member
**Severity:** P3
**Where:** spec.md:57-62 (`_is_ingestion`); spec.md:217-219 (alias layer); spec.md:236 (`test_unknown_mcp_wire_name_poisoned_result_is_flagged`)
**Claim:** Unknown MCP wire names are result-scanned. Ingestion uses `canonicalize_tool_name` only; aliases are not auto-excluded.
**Why this is wrong:** `canonicalize_tool_name` strips one `mcp__<server>__` prefix (`normalize.py:175`, `:225`; `test_guard.py:558`). `_is_ingestion` then tests `_NON_INGESTING_CANON`. `mcp__files__write_file` / `mcp__foo__memory` become `write_file` / `memory` and are skipped. The MCP test uses `mcp__some_server__some_tool` → `some_tool`, which does not catch this. Same PET-118 contract as today’s inclusion set; worth recording as a residual so it is not “fixed” by skipping canonicalize.
**Suggested fix:** One sentence under Decision 2 or 6: exclusion is on the canonical bare name; an MCP wire name that strips onto an exclusion member is treated as that Hermes tool. Do not skip canonicalize.

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 1 | P4: 0

STATUS: GREEN
