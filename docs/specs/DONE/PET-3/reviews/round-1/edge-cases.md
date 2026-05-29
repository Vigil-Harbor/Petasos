# Edge-Cases Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: Thread-safety race in `_ensure_loaded()` under concurrent `scan()` calls
**Severity:** P1
**Where:** spec.md:99-112 (Lazy-load mechanism)
**Edge case:** Two `scan()` calls arrive concurrently on different asyncio tasks. Both check `self._loaded`, both see `False`, both enter `_ensure_loaded()` simultaneously.
**What happens:** Both threads instantiate sub-scanners and assign to `self._scanners`. Duplicate model loads waste ~360MB of RAM. A second caller could see `_loaded == True` while `_scanners` is still empty or partially populated.
**Suggested fix:** Add a `threading.Lock` around `_ensure_loaded()` to serialize the lazy-load.

### F-2: `_scan_sync` return type does not carry per-sub-scanner errors back to `ScanResult`
**Severity:** P1
**Where:** spec.md:130-159 (scan() flow and _scan_sync)
**Edge case:** One sub-scanner raises an exception mid-loop. The pseudocode shows `_scan_sync` returning only `findings`. The `scan()` flow constructs `ScanResult` with no error plumbing for partial failures.
**Suggested fix:** Update `_scan_sync` to return `tuple[list[ScanFinding], list[str]]` (findings and errors). Update `scan()` to unpack both.

### F-3: `enable_ban_topics=True` with `ban_topics=None` will crash at LLM Guard level
**Severity:** P1
**Where:** spec.md:76-84 (Constructor), spec.md:125 (BanTopics registry)
**Edge case:** `LlmGuardScanner(enable_ban_topics=True)` without providing `ban_topics`. LLM Guard's `BanTopics` constructor requires `topics=` as a non-empty list. Entire scanner load fails, losing all sub-scanners.
**Suggested fix:** Add precondition: if `enable_ban_topics=True` and `ban_topics` is None/empty, raise `ValueError` at construction time. Add test case.

### F-4: No validation of `threshold` parameter range
**Severity:** P2
**Where:** spec.md:75-76 (Constructor)
**Edge case:** `threshold=-0.5`, `threshold=1.5`, `threshold=float('nan')` produce undefined behavior.
**Suggested fix:** Add precondition: `0.0 < threshold <= 1.0`, raise `ValueError` otherwise.

### F-5: Empty string input to `scan()`
**Severity:** P2
**Where:** spec.md:130-157 (scan() flow)
**Edge case:** `scan("")` triggers model downloads (180MB) for zero content.
**Suggested fix:** Document that empty-string scan is valid but consider short-circuiting.

### F-6: `_ensure_loaded()` failure leaves `_loaded` state ambiguous on retry
**Severity:** P1
**Where:** spec.md:105-112 (Lazy-load mechanism)
**Edge case:** Import succeeds but model instantiation fails (network, disk full). `_loaded` remains `False`. Every subsequent `scan()` retries the expensive operation. Persistent errors cause hundreds of retries.
**Suggested fix:** Add `_load_error: str | None` field. On load failure, cache the error. On subsequent calls, return cached error immediately.

### F-7: `ScanResult` is frozen but spec describes building it with accumulated error string
**Severity:** P2
**Where:** spec.md:135-137, petasos/_types.py:67-72
**Edge case:** Frozen dataclass prevents post-construction mutation. Success-path `ScanResult` constructor omits `error=`.
**Suggested fix:** Same plumbing fix as F-2.

### F-8: Very large input text passed to `asyncio.to_thread`
**Severity:** P2
**Where:** spec.md:134
**Edge case:** Multi-megabyte string causes DeBERTa OOM or truncation.
**Suggested fix:** Document that LlmGuardScanner does not enforce input size limits (pipeline-level enforcement).

### F-9: `direction="outbound"` test only checks non-crash
**Severity:** P3
**Where:** spec.md:204 (Test 20)
**Suggested fix:** Strengthen test to assert findings are still produced.

### F-10: `__init__.py` re-export hides unexpected import errors
**Severity:** P3
**Where:** spec.md:163-171
**Suggested fix:** Optionally log a warning.

### F-11: `isinstance` check passes for non-async scan
**Severity:** P3
**Where:** spec.md:183 (Test 1)
**Suggested fix:** Add `inspect.iscoroutinefunction` assertion.

### F-12: No test for model download failure
**Severity:** P3
**Where:** spec.md:177-209
**Suggested fix:** Add a unit test patching PromptInjection.__init__ to raise.

## Summary
P0: 0 | P1: 3 | P2: 3 | P3: 4 | P4: 0

STATUS: RED P0=0 P1=3 P2=3 P3=4 P4=0
