# Edge-Cases Review — round 1

## Closure of round 0 findings
N/A — round 1

## Findings

### F-1: `to_thread(Lock.acquire)` plus `_run_async` cancel leaks `_inspect_lock`
**Severity:** P1
**Where:** spec.md:109-113 (Decision 12), spec.md:220 (evaluate takes the lock the same way)
**Edge case:** Ingest head `inspect()` holds `_inspect_lock` across Stage 2 (bare `await` of sync regex) and ML `wait_for`. `_pre_tool_call` submits `await asyncio.to_thread(_inspect_lock.acquire)` then `_guard.evaluate` onto `_async_loop` via `_run_async` (default 15 s, cancel-and-re-raise at `reference_plugin/__init__.py:474-476`). Same pattern on `_maybe_reconfigure` → `_run_async(_apply_reconfigure)` (`:1642`). Legal `scanner_timeout_seconds` is `(0, 60]` (`config.py:325-332`); at any value > 15 the head can hold the lock past evaluate's timeout. A ReDoS in the first 2,048 characters does it even at the default 10 s.
**What happens:** `future.cancel()` injects `CancelledError` at `await to_thread(...)`. `asyncio.to_thread` / `run_in_executor` does not abort the worker. The worker can still return from `Lock.acquire()` after the coroutine is gone; the `finally: release()` never runs. Every later evaluate and ingest-head inspect then blocks forever on the leaked lock. `_pre_tool_call`'s `except Exception: return None` (`:1963-1966`) fail-opens the parameter fence permanently — not for the duration of one wedge.
**Why the spec misses it:** Decision 12 correctly forbids a blocking `acquire()` on `_async_loop` and pins `to_thread` so the loop yields. It never pins a cancel-safe acquire. `_run_async` always cancels on timeout. Decision 14 records "mutex held across the head's ML await" as residual coupling, which covers a bounded wait, not a leaked lock. Isolation only moved the 1e6 sweep off the lock; the head's uninterruptible Stage 2 still sits under it.
**Suggested fix:** Pin a leak-proof protocol, e.g. host-thread `acquire(timeout=…)` around `_run_async(_guard.evaluate)` with `release()` in `finally`, and the same timeout-acquire inside `_apply_reconfigure`'s worker so a cancelled waiter never takes ownership. Do not `cancel()` a future whose only await is `Lock.acquire()`. Switch `_maybe_reconfigure` to the existing fire-and-forget `_dispatch_reconfigure` so apply is not under `_run_async`'s 15 s cancel. Add a test: time out evaluate while it is waiting for the lock; assert a later `_pre_tool_call` still gets a guard decision, not the fail-open path.

### F-2: cancelled `inspect()` is swallowed; the helper sweep then runs with no deadline
**Severity:** P1
**Where:** spec.md:191-199 (helper steps 3–5, never-throws), spec.md:214 (`_run_ingest_async` cancel-and-re-raise)
**Edge case:** Outer `_run_ingest_async` times out (budget `scanner_timeout+5s`, cap 65 s) while the helper is in `await pipeline.inspect(head)`.
**What happens:** `Pipeline.inspect` catches `BaseException` (`pipeline.py:672-684`) and returns `PipelineResult(errors=("CancelledError: …",))`. `_scan_one` also catches `BaseException` (`:272-280`), so cancellation is consumed inside inspect and the Task is no longer cancelled. The helper has no check of `head.errors` / task-cancelled between step 3 and the sweep, so it walks all remaining chunks. The host already raised `TimeoutError` and the plugin already returned `ingest_unscanned`. The leftover sweep has no timeout: a ReDoS in a later chunk occupies the K=1 ingest loop until process death, and every subsequent result scan queues behind it and times out.
**Why the spec misses it:** Existing `_run_async` comments treat inspect swallowing cancel as "freeing the loop." That was true when inspect was the whole job. The helper adds 18 `MinimalScanner.scan` calls after inspect. "Never throws" plus the raising-inspect unit test push implementers to treat any inspect outcome as continue-to-sweep.
**Suggested fix:** After `await pipeline.inspect(...)`, if the current task is cancelled or `head.errors` names `CancelledError`, skip the sweep, release `_inspect_lock`, and return. Do not catch `BaseException` in the helper. Add a test: cancel the helper during inspect; assert `_chunk_origins` / `MinimalScanner.scan` is not entered afterwards.

### F-3: chunk / floor errors still report `coverage=full` with a silent gap
**Severity:** P1
**Where:** spec.md:191-199, spec.md:141-148 (coverage table), spec.md:216 (floor-error still `ingest_unscanned`)
**Edge case:** (1) A chunk's `MinimalScanner.scan` returns `ScanResult.error` — `scan()` catches `Exception` (`minimal.py:628-635`). The realistic trigger is a lone surrogate: `_check_structural` does `text.encode("utf-8")` (`:693`) which raises `UnicodeEncodeError` on `\ud800`. Windows paths and some JSON blobs produce those. (2) Head inspect's floor `error` is set the same way. Today the plugin keys `ingest_unscanned` on `scan.scanner_results` / `floor.error` (`reference_plugin/__init__.py:2351-2360`). `IngestionScanResult` has `findings`, `coverage`, `head`, `errors` — no `scanner_results`.
**What happens:** Spec step 5 maps findings and ignores `ScanResult.error`. Coverage still says `full` / `scanned_chars=len(covered)`. The plugin rewrite partitions `scan.findings` on "a successful helper result." A surrogate (or any `_scan_impl` exception) in one 64 KiB window is a hole below the ceiling with no banner, no `ingest_unscanned`, no `errors[]` entry. Head floor.error is only reachable via `scan.head.scanner_results`; if the implementer does not re-wire that, a failed syntactic floor on the head becomes a clean pass-through — PET-170's honesty path silently dropped. Both contradict Done-when "no unscanned gap below the stated ceiling."
**Why the spec misses it:** "Never throws" is specified; per-chunk `ScanResult.error` is not. Floor-error is named as unchanged but the object it used to read is being replaced. Test plan covers raising `inspect()`, ceiling slice, and midpoint, not an errored chunk or `head.scanner_results[-].error`.
**Suggested fix:** Append every chunk `error` (and head floor.error) to `IngestionScanResult.errors`. If any covered window failed to scan, the plugin takes the existing `ingest_unscanned` / `scan_unavailable` path (or a named `cause=chunk_error`) and must not emit `coverage=full`. Pin tests: lone surrogate in chunk 2; head floor.error still banners `scan_unavailable` even when other chunks have findings.

### F-4: ceiling-clean banner reuses the "injection found" findings boilerplate
**Severity:** P1
**Where:** spec.md:146, spec.md:227, `petasos/session/formatting.py:49-53`
**Edge case:** `len(result) > 1_000_000`, helper returns no HIGH+ non-PII findings. Plugin is told to call `format_result_notice(path="findings", finding=None, finding_count=0, scanned_chars=1_000_000, total_chars=len(result), coverage="ceiling")`.
**What happens:** Line 1 is still `_RESULT_NOTICE["findings"]`: "Petasos scanned the content below and found patterns that match known prompt-injection techniques." Line 2 is omitted (`finding is None`). Coverage + `Scanned 1000000 of N` append. A clean 1,000,001-char file is presented to the model as a confirmed injection. That is the opposite of PET-170 banner honesty (and of the spec's own "no HIGH+ non-PII" / `finding_count=0` setup). `test_none_finding_omits_the_rule_line_entirely` already shows this contract: path=`findings` with `finding=None` still carries the injection sentence.
**Why the spec misses it:** It reuses `path="findings"` to get line 3 (`Scanned X of Y`) and a new coverage line, and never changes line 1. Formatting tests only assert "coverage + scanned/total, no top-finding line."
**Suggested fix:** Add a `ResultNoticePath` value (e.g. `"ceiling"`) whose line 1 says the first 1,000,000 characters were scanned and the rest is unverified — not that injection was found. Keep `scan_unavailable` for true scan failure. Assert the injection sentence is absent on the ceiling-clean fixture.

### F-5: max-size base64 blobs can split; residual names only hex
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:88-91 (Decision 8)
**Edge case:** A base64 blob of `_DECODE_MAX_BYTES` (8,192 decoded bytes ≈ 10,924 encoded chars) straddles a chunk cut. Overlap is 8,192 *characters*. Decision 8 already computes "base64 of an 8,192-byte decode is ~10,923 chars; hex is 16,384" then names only hex as residual. The straddle acceptance test "uses the injection phrase, not a max hex blob."
**What happens:** Neither chunk contains a complete decodable blob (`CHUNK_CHARS=65,536` does not save a 10,924-char span that crosses the cut). Decode-and-rescan misses an encoded injection below the ceiling. Same class as the named hex residual; base64 is the common carrier (`minimal.py:401-413`).
**Why the spec misses it:** The parenthetical includes both encodings; the residual sentence names only hex. An implementer will treat base64 as closed.
**Suggested fix:** Name every expansion codec whose encoded length of `_DECODE_MAX_BYTES` exceeds `CHUNK_OVERLAP_CHARS` (base64 and hex at minimum) as a residual, or raise overlap to `ceil(8192 * 4/3)` padded plus hex if that is meant to be closed. Keep the injection-phrase straddle test; do not claim decode-rescan coverage the overlap does not buy.

### F-6: test helpers still stub `_run_async`; isolation patch can re-take the lock
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:233-241 (isolation test), spec.md:255-267; `tests/test_reference_plugin_tool_result.py:153-174`
**Edge case:** (1) `_plugin()` replaces `_run_async` with `asyncio.run` and leaves a new `_run_ingest_async` live. Almost every existing `_transform_tool_result` test goes through `_plugin`. (2) Isolation test says "Monkeypatch the helper's `MinimalScanner.scan` (or the private scanner the helper builds)." A class-level patch also wraps `pipeline.inspect`'s Stage 2, which holds `_inspect_lock`.
**What happens:** (1) Stub-pipeline tests start a real ingest thread, or hang, or stop recording `inspect` calls because those now happen inside `_run_ingest_async`. (2) Class-level patch makes `_pre_tool_call` wait on the lock and take the 15 s fail-open path — the isolation pin fails even when K=1 is correct. `tests/test_enforcement_events.py:899,948` fixtures still say `truncated=True, scanned=8000`; those are synthetic clip-overrun strings (`_MAX_REASON_LEN=200`). Shortening the suffix to `coverage=full` can drop them under the cap and skip the clip path they exist to test.
**Why the spec misses it:** The test plan lists new cases and deletions, not the `_plugin` twin-stub or a private-scanner-only patch. The enforcement-events line reads as "keep the old keys."
**Suggested fix:** `_plugin` must stub `_run_ingest_async` the same way it stubs `_run_async`. Isolation must patch the helper's private instance (identity inequality already in the unit plan), not `MinimalScanner.scan`. Keep enforcement-event fixtures long enough to overrun `_MAX_REASON_LEN`; the old `truncated=` keys can stay in those synthetic strings.

## Summary
P0: 0 | P1: 4 | P2: 2 | P3: 0 | P4: 0

STATUS: RED P0=0 P1=4 P2=2 P3=0 P4=0
