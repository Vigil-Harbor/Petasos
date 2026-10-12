# Edge-Cases Review — round 1

## Closure of round 0 findings
N/A — round 1

## Findings

### F-1: Floor-copy failure drops the unavailable banner
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec § Decision 3 (spec.md:54-58); spec § Design helper snippet (spec.md:100-112); plugin floor walk left unchanged (spec.md:120-132)
**Edge case:** `pipeline.inspect()` returns a head, and the minimal-floor copy walk raises. Reachable inputs are a non-iterable `scanner_results`, a raising `scanner_name`, or a raising `.error`. A real frozen `ScanResult` does not do this. The new `except` exists only for this walk.
**What happens:** The helper appends the error, leaves `inspect_failed` false, and keeps `head`. `_transform_tool_result` then repeats that walk, unguarded, at `docs/deployment/reference_plugin/__init__.py:2418-2423` (`723cdc5`) and again on `floor.error` inside the cause chain. That exception is not a scan cause. It hits the outer handler at `:2526-2532`, which logs `PETASOS_RESULT_SCAN_ERROR` and `return None`. No scan-unavailable banner and no `ingest_unscanned` event. The original tool text is passed through with no annotation.
**Why the spec misses it:** Today the copy sits in the same `try` as `inspect` (`petasos/session/ingest.py:150-162` at `723cdc5`). Any raise sets `head = None`, and the plugin classifies `boundary` and returns the banner. Decision 3 says to keep that head so "floor and sweep classification then see the head they already key on." The plugin snippet never wraps the second walk, so the input that enters the new `except` never gets that far.
**Suggested fix:** In the floor-copy `except`, record the error, set `head = None`, and leave `inspect_failed` false. Drop the claim that classification still sees that head. If a good head must be preserved, guard the plugin walk at `:2418-2423` and on failure assign `boundary` (or `sweep_error` from `scan.errors`) instead of escaping to `return None`. Add a pin: a head whose `scanner_results` iteration raises still returns the banner, with `inspect_failed` false and `cause` not `inspect_error`.

### F-2: Lock-acquire and floor-copy misses are not pinned
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec § Decision 3 (spec.md:54-58); spec § Test plan (spec.md:144-170)
**Edge case:** `_acquire_inspect_lock` raises `Exception` before `inspect`, or the floor-copy walk raises after a normal `inspect` return. Neither is a raising `inspect()`, a floor `error` string, or a chunk failure.
**What happens:** The specified control flow keeps `inspect_failed` false. A lock failure leaves `head is None` and the plugin emits `cause=boundary`. A floor-copy failure is F-1. The new asserts only cover a raising `inspect` (`inspect_failed` true), `test_head_floor_error_is_recorded_even_when_sweep_finds_injection` (`:185`), and `test_failed_chunk_scan_is_recorded_and_does_not_raise` (`:148`). Those stay green if the flag is also set on the lock `except` or the floor-copy `except`. A lock failure would then be logged as `inspect_error`.
**Why the spec misses it:** Decision 3 is the reason the single `try` is split, and Out of scope says lock failure stays `boundary`. The test plan never drives either exception. `threading.Lock.acquire(blocking=False)` does not raise in production, so no existing pin hits it. The held-lock plugin test expects `cause=timeout`, which is the budget path, not a raising acquire.
**Suggested fix:** Pin both. A lock helper that raises `RuntimeError` yields `inspect_failed is False`, `head is None`, one `ingest_unscanned` with `cause=boundary`, and the banner. A returned head whose `scanner_results` walk raises yields `inspect_failed is False` and the unavailable banner, not `None`. Keep these out of the six-cause parametrization.

### F-3: The inspect exception class is discarded
**Severity:** P3
**Where:** spec § Decision 2 (spec.md:46-50); spec § Design plugin (spec.md:136)
**Edge case:** `inspect()` raises `RuntimeError("inspect exploded")` (or any other `Exception`) and the helper returns. The operator log and the spool row are the only durable record.
**What happens:** The helper stores `f"{type(exc).__name__}: {exc}"` on `errors`, then `_transform_tool_result` drops the result. `_log_ingest_unscanned` (`reference_plugin/__init__.py:1362-1368` at `723cdc5`) logs `cause` and `len` only. The event reason is `cause=inspect_error` and must not contain `RuntimeError`. A later debugger cannot tell `RuntimeError` from `AttributeError`.
**Why the spec misses it:** Decision 2 correctly forbids choosing `cause` by parsing that string. It still calls the string diagnostic, but the only production caller is forbidden to read it, and the spec does not add a log. The class name never leaves the process.
**Suggested fix:** State that the message stays out of `reason`. Have the helper log the exception class name on the existing `PETASOS_INGEST_UNSCANNED` path, or add one bounded class token that is not an input to the cause chain. Do not substring-match `errors`.

### F-4: `with_finding` never shows the sweep matched
**Severity:** P3
**Where:** spec § Test plan (spec.md:150-162)
**Edge case:** The `with_finding=true` payload is supposed to make the real syntactic sweep produce a HIGH+ finding while `inspect` raises. At `723cdc5`, `_INJECTION` ("Ignore all previous instructions…") does match `ignore-previous` at `Severity.HIGH`. The plugin test never observes that finding.
**What happens:** `ingest_flagged` is also empty when the sweep matches nothing, because `head is None` already suppresses findings today. If `_INJECTION` stops matching, or the sweep is skipped, the arm still passes as long as `cause=inspect_error` and the event list is empty. It does not lock the PET-209 coexistence case the brief requires.
**Why the spec misses it:** The plugin discards findings once `cause` is set, and the new test only reads the return string and the event spool. Nothing asserts that this payload actually produced a blocking finding under a raising `inspect`.
**Suggested fix:** In the `with_finding` arm, call the real helper on the same text and assert `inspect_failed is True`, `head is None`, and at least one finding with severity HIGH or worse. Then assert the plugin emits `cause=inspect_error` and no `ingest_flagged`.

## Summary
No new persisted record, so the persistence checklist does not apply. Plane PET-205 was retrieved (Backlog). The spec has no `## Deferred — follow-up required` section. Control flow was checked at `723cdc5956d024195b3b3afdde09004618266aa6`, not the working tree. Real `Pipeline.inspect` still catches `BaseException` and returns an empty `scanner_results` result. That shape stays `cause=boundary` under Decision 1, and `inspect_error` is only the propagating raise. That split matches the brief. The hole is the floor-copy `except` that keeps an unwalkable head and lets the plugin fail open.
P0: 0 | P1: 0 | P2: 2 | P3: 2 | P4: 0

STATUS: GREEN
