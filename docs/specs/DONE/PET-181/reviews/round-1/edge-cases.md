# Edge-Cases Review — round 1

## Closure of round 0 findings
N/A — round 1

## Findings

### F-1: Cadence keys are not uniformly type-guarded; a raise in the helper swallows the banner
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:104–111 (Decision 5 key order); spec.md:199–209 (helper sits inside the outer `try`); `docs/deployment/reference_plugin/__init__.py:2356-2362` (fail-open `return None`)
**Edge case:** Host `session_id` / `task_id` that is missing, `""`, whitespace-only, `None`, a UUID, an int, or an unhashable (list/dict). Hermes production shape is `session_id=session_id or ""` (`hermes-agent-PET-158/model_tools.py:1398`) — key **present**, value empty str — not omitted.
**What happens:** Step 1 type-checks `session_id` as a non-empty `str`. Step 2 is only “`task_id` if truthy.” A truthy non-str used as a dict key raises `TypeError`. That raise is caught by the handler’s outer wrapper, which logs `PETASOS_RESULT_SCAN_ERROR` and **returns `None`** — content passed through, **banner gone**. Decision 5’s “never suppress the banner” is then false. Hermes `session_id=""` is also untested: the uncorrelated test is “no `session_id`,” which is not the hook payload.
**Why the spec misses it:** The type guard is written for step 1 only. The Design snippet places `_log_ingest_unscanned` in the same `try` as the scan, so a helper exception takes the banner with it. Test plan does not pin `session_id=""`, `session_id=None`, or a non-str.
**Suggested fix:** Type-check every cadence key the same way (`isinstance(..., str) and s.strip()` or equivalent). Treat Hermes `session_id=""` as fall-through, identical to omitted. Isolate cadence+event in an inner `try` so the `format_result_notice(...) + result` return always runs. Add tests for `session_id=""`, omitted, `None`, and a non-str.

### F-2: Cadence step 3 re-looks up `_session_ids`; a miss dumps a live desktop session into `"uncorrelated"`
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:108–109 (Decision 5 step 3); spec.md:111 (`_ingest_unscanned_cadence_key`); `__init__.py:936-951` (`_derive_session_id` + `_bypass_lock`); `__init__.py:2209` (derive runs before the scan)
**Edge case:** No host `session_id`, empty `task_id`, `_agent` is not None — the Hermes Desktop shape — and the cadence helper looks up `_session_ids` without `_bypass_lock`, or the lookup misses.
**What happens:** By the time cadence runs, `_derive_session_id` has already stored `desktop-{uuid12}` under `_bypass_lock`. Re-lookup without the lock is a concurrent-dict race. A miss (reset in tests; theoretically a map replace) falls through to step 4 and shares the process-global `"uncorrelated"` clock with every uncorrelatable caller — over-suppressing `ingest_unscanned` for that desktop session and for everyone else on the bucket. Minting a second id would re-open the per-call cap no-op Decision 5 exists to close.
**Why the spec misses it:** “Same lookup `_derive_session_id` uses; do not mint a second id” never says “on miss, do not fall through to `"uncorrelated"`” and never says to take `_bypass_lock`. The helper already receives the derived `session_id`.
**Suggested fix:** When `_agent is not None`, use the already-derived `session_id` argument (it *is* the desktop uuid). Do not re-read `_session_ids`. Pin with a two-call same-`_agent` test and a different-`_agent` test.

### F-3: Host `session_id` must not arm PET-176 D6; no test pins `inspect(session_id=None)` on that shape
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:111 (correlator contract); spec.md:2235-2258 of current plugin (`correlatable = bool(task_id) or kwargs.get("_agent") is not None`); spec.md:246–247 (cadence tests)
**Edge case:** Host passes a stable `session_id=` with empty `task_id` and no `_agent`. Cadence correctly groups on that string. Frequency still must not accumulate under it (PET-176 D6 / Decision 5 last paragraph).
**What happens:** An implementer who “helpfully” adds host `session_id` to `correlatable` starts creating tracker rows, consuming `max_new_sessions_per_minute`, and arming session-keyed alerts under a key `_derive_session_id` never used — the exact silent correlator change this ticket forbids. Cadence tests as written only check WARNING/event clocks, not `stub.calls[].session_id`.
**Why the spec misses it:** The invariant is stated in Decision 5 and Out of scope, but the test plan does not assert `inspect(..., session_id=None)` when only `session_id=` is present. `"uncorrelated"` as a cadence bucket is easy to confuse with `PETASOS_INGEST_UNCORRELATED` (`__init__.py:1404`).
**Suggested fix:** Extend the host-`session_id` cadence test: two calls share the log clock **and** both `inspect` calls still receive `session_id=None` / `weight_cap=0.0`. Leave `_note_uncorrelated_ingest` on the input shape (`not task_id and _agent is None`), not on the cadence key.

### F-4: MCP wire names that canonicalize onto an exclusion member are silently excluded
**Severity:** P2
**Where:** spec.md:57–62 (`_is_ingestion`); spec.md:236 (`test_unknown_mcp_wire_name_poisoned_result_is_flagged`); `petasos/normalize.py:175,206-227`
**Edge case:** `tool_name="mcp__acme__write_file"` (or `__patch` / `__todo` / `__memory` / `__kanban_create` / `__kanban_comment`). `_NAMESPACE_PREFIX_RE` strips one `mcp__<ns>__` prefix; canon is the exclusion member.
**What happens:** Invert’s promise — “unknown MCP names scan” — is false for any MCP tool whose bare name matches `NON_INGESTING_TOOLS`. Result is skipped with `PETASOS_INGEST_EXCLUDED`, not scanned. The planned MCP test uses `mcp__some_server__some_tool`, which does not collide.
**Why the spec misses it:** Canonicalize-as-identity is a PET-118 invariant, but invert makes exclusion membership the gate, so a name collision is a new fail-open. Not pinned, not recorded as a residual (unlike Decision 4’s lint/LSP residual).
**Suggested fix:** Pin `mcp__acme__write_file` (and one other exclusion member) as excluded-by-canonicalize, and record it next to Decision 3 as intended identity, not “unknown MCP.” If that is unacceptable, exclusion must match on the raw wire name, not the canon.

### F-5: Blank-name floor test can pass via gate 2 without exercising gate 3
**Severity:** P2
**Where:** spec.md:186–189 (gate 3 empty-canon branch); spec.md:239 (`test_blank_tool_name_is_not_scanned`); `__init__.py:2173` (`if not isinstance(result, str) or not result`)
**Edge case:** `tool_name=""` or whitespace with `result=""` (or any falsy/non-str result).
**What happens:** Gate 2 returns `None` first. After invert `_is_ingestion("")` is False, so there is also no `PETASOS_INGEST_NOT_STRING`. The test’s “no scan, no `PETASOS_INGEST_EXCLUDED`” passes without ever hitting the named-tool floor Decision 6 owns. A regression that scans blank names on non-empty strings would still be green if the test used an empty result.
**Why the spec misses it:** The test plan does not require a non-empty string result.
**Suggested fix:** Drive `result="content"` (and a whitespace `tool_name` that canonicalizes to `""`). Assert `stub.calls == []`, no `PETASOS_INGEST_EXCLUDED`, no `PETASOS_INGEST_NOT_CLASSIFIED`. Optionally a second case with `result=""` to show gate 2 still wins.

### F-6: Gate 2 still hides excluded tools whose result is empty or non-string
**Severity:** P3
**Where:** spec.md:183 (keep gate order); spec.md:186–189 (EXCLUDED only on the gate-3 path); `__init__.py:2173-2183`
**Edge case:** `write_file` / `patch` / kanban tools returning `""`, a dict, or `None`.
**What happens:** `_is_ingestion` is False, so gate 2 returns silently. `PETASOS_INGEST_EXCLUDED` never fires. Decision 7’s “exclusion set must be falsifiable in a live deploy” does not hold for those shapes. Hermes `write_file` success is non-empty JSON, so this is unlikely on the happy path.
**Why the spec misses it:** Gate order is preserved without stating that EXCLUDED is string-result-only.
**Suggested fix:** One-line note in Decision 7 / gate-3: EXCLUDED is for a non-empty string result of an excluded canon; empty/non-string excluded tools stay silent at gate 2.

### F-7: First-sighting cap 512 now bounds an unbounded gate-2 population
**Severity:** P3
**Where:** spec.md:113 (“First-sighting skip keys stay capped at 512”); `__init__.py:189-197`; Decision 7 (NOT_STRING fires for newly scanned unknowns)
**Edge case:** After invert, every unknown MCP name with an empty or dict result hits `_note_ingest_skip`. Unique `(canon[:64], kind)` pairs are unbounded; the cap was sized for the ~81-tool census.
**What happens:** Drop-oldest. New tools still log (duplication, not suppression). Live `vision_analyze` / `browser_vision` dict latches can be evicted and re-log. DEBUG only; no crash.
**Why the spec misses it:** Cap reuse is stated, not re-justified against the inverted population.
**Suggested fix:** One sentence that 512 still bounds memory, eviction duplicates DEBUG, and the exclusion set (8 names) cannot fill it.

## Summary
P0: 0 | P1: 0 | P2: 5 | P3: 2 | P4: 0

STATUS: GREEN
