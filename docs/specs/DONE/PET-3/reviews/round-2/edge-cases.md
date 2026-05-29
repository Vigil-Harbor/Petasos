# Edge-Cases Review -- round 2

## Closure of round 1 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| edge-cases | F-1 | Thread-safety race in `_ensure_loaded()` | CLOSED | Spec D3a (line 53-55) adds `threading.Lock` with double-checked locking; code block at lines 130-143 shows the pattern |
| edge-cases | F-2 | `_scan_sync` return type doesn't carry errors back | CLOSED | Spec line 190: `_scan_sync` returns `tuple[list[ScanFinding], list[str]]`; scan() flow at line 177 unpacks `findings, errors`; line 181 joins errors |
| edge-cases | F-3 | `enable_ban_topics=True` with `ban_topics=None` crashes | CLOSED | Spec lines 98-101: constructor raises `ValueError` eagerly; test 11 (line 258) covers both `None` and `[]` cases |
| edge-cases | F-4 | No validation of `threshold` parameter range | CLOSED | Spec Deferred (P2+) section at line 334 explicitly acknowledges and defers; severity was P2, deferral is acceptable |
| edge-cases | F-5 | Empty string input to `scan()` | CLOSED | Spec Out of Scope line 326: "Empty input short-circuit -- `scan("")` is valid and runs through sub-scanners normally. No special-case optimization." |
| edge-cases | F-6 | `_ensure_loaded()` failure left `_loaded` state ambiguous on retry | CLOSED | Spec D3b (lines 58-59) adds `_load_error: str | None`; code block lines 133-134 short-circuit on cached failure; `reset()` at lines 145-150 clears both |
| edge-cases | F-7 | `ScanResult` is frozen but spec describes building with accumulated error string | CLOSED | Spec lines 177-183 construct `ScanResult` with `error="; ".join(errors) if errors else None` as a constructor arg, not mutation; consistent with frozen dataclass |
| edge-cases | F-8 | Very large input text passed to `asyncio.to_thread` | CLOSED | Spec Out of Scope lines 325: "LlmGuardScanner does not enforce input size limits; that's the pipeline's responsibility (PET-6)" |
| edge-cases | F-9 | `direction="outbound"` test only checks non-crash | CLOSED | Spec test 24 (line 274): "completes without error and still produces findings for known-detectable input" |
| edge-cases | F-10 | `__init__.py` re-export hides unexpected import errors | CLOSED | Spec Deferred section line 335-336 explicitly acknowledges as P2 |
| edge-cases | F-11 | `isinstance` check passes for non-async scan | CLOSED | Spec test 1 (line 249): "additionally `inspect.iscoroutinefunction(scanner.scan)` is True" |
| edge-cases | F-12 | No test for model download failure | CLOSED | Spec test 14 (line 261): "patch `PromptInjection.__init__` to raise `RuntimeError('model download failed')`" |
| correctness | F-1 | `_scan_sync` code block contradicts prose on error isolation | CLOSED | Spec lines 193-211: code block now includes try/except per iteration with `errors.append(f"{rule_id}: {exc}")` |
| correctness | F-2 | `scan()` flow has no path for partial-failure errors to reach `ScanResult.error` | CLOSED | Spec line 177: `findings, errors = await asyncio.to_thread(self._scan_sync, text)` and line 181: `error="; ".join(errors) if errors else None` |
| correctness | F-3 | `enable_ban_topics=True` with `ban_topics=None` | CLOSED | Spec lines 98-101: `ValueError` raised eagerly |
| correctness | F-4 | "20-message corpus" done-when has no corresponding test | CLOSED | Spec done-when line 305-306 now says "10 detection scenarios with distinct adversarial inputs", matching actual test plan |
| correctness | F-5 | Test command hardcodes `python3.13` | CLOSED | Spec line 286: `pytest tests/test_llm_guard_scanner.py -v` (no version prefix) |
| conventions | F-1 | `rule_id` naming inconsistency -- missing sub-category segment | CLOSED | Spec line 167: explicit note acknowledging three-segment vs four-segment difference with rationale |
| conventions | F-2 | `_ensure_loaded` is not thread-safe, unlike PET-4 | CLOSED | Spec D3a adds `threading.Lock` double-checked locking |
| conventions | F-3 | `scanners/__init__.py` re-export pattern diverges from PET-4 | CLOSED | Spec lines 218-232: uses `try/except ImportError: pass` with `__all__`; note added at line 233 explaining choice |
| conventions | F-4 | Test command specifies `python3.13` | CLOSED | Spec line 286: `pytest tests/test_llm_guard_scanner.py -v` |
| conventions | F-5 | Unit tests mock import machinery contradicting CLAUDE.md wording | CLOSED | Spec lines 246-248: note clarifying "unit tests mock the import and sub-scanner layers" vs "Scanner protocol boundary" |
| conventions | F-6 | Done-when "20-message corpus" not reflected in test plan | CLOSED | Done-when updated to "10 detection scenarios" |
| conventions | F-7 | Per-sub-scanner error isolation without brief authorization | CLOSED | Noted implicitly by spec prose at line 214 |
| conventions | F-8 | D3 threading strategy without brief authorization | CLOSED | Spec line 51: "Spec addition (not in brief)" note present |
| conventions | F-9 | Spec omits `petasos/__init__.py` from modified files | CLOSED | Spec lines 26-27: "Files left alone" section includes `petasos/__init__.py` with rationale |
| conventions | F-10 | Code samples omit `from __future__ import annotations` | CLOSED | Spec lines 85, 122: code samples include the import; Deferred section line 337 notes convention |

## Findings

### F-1: `_ensure_loaded()` double-checked locking checks `_load_error` outside the lock but not inside
**Severity:** P1
**Where:** spec.md:130-143 (Lazy-load mechanism code block)
**Edge case:** Thread A and Thread B both call `_ensure_loaded()` concurrently. Both pass the `self._loaded` check (line 131, `False`) and the `self._load_error` check (line 133, `None`). Thread A acquires the lock. Thread A's load fails, sets `self._load_error = str(exc)` (line 143), releases the lock. Thread B acquires the lock. Thread B passes the `if self._loaded: return` check at line 136 (still `False`). There is no check for `_load_error` inside the lock. Thread B re-executes the expensive, failing load operation. The error is cached again (same outcome), but the spec's stated goal of "subsequent calls return the cached error immediately without retrying" (D3b, line 59) is violated for concurrent calls that are already past the outer guard.
**What happens:** Redundant expensive load attempt under concurrent access. Not a data corruption issue, but contradicts the "don't retry expensive load" design intent and wastes resources (model download, import, etc.).
**Why the spec misses it:** The double-checked locking pattern correctly guards `_loaded` inside the lock (line 136-137) but does not replicate the `_load_error` guard that exists outside the lock (line 133-134).
**Suggested fix:** Add `if self._load_error is not None: return` immediately after the `if self._loaded: return` check inside the `with self._lock:` block (between lines 137 and 138).

### F-2: `reset()` called concurrently with `scan()` can cause `_scan_sync` to run against an empty `_scanners` list
**Severity:** P1
**Where:** spec.md:145-150 (reset method), spec.md:169-186 (scan() flow)
**Edge case:** Thread A is executing `scan()`. It passes `_ensure_loaded()` (line 174) and confirms `_load_error is None` (line 175-176). Between lines 176 and 177, Thread B calls `reset()`, which acquires the lock and sets `_loaded = False`, `_scanners = []` (lines 149-150). Thread A then dispatches `asyncio.to_thread(self._scan_sync, text)` with an empty `_scanners` list. The result is an empty findings list and no error, which is a silent false-negative -- the scanner reports the input as clean when it was never actually scanned.
**What happens:** Silent false-negative. Content that should be flagged passes without findings and without error. This is a content-security correctness failure.
**Why the spec misses it:** `reset()` is protected by the lock for its own internal consistency, but `scan()` reads `_scanners` outside the lock (after `_ensure_loaded()` returns). There is no mechanism to prevent `reset()` from invalidating the state between `_ensure_loaded()` and the actual use of `_scanners`.
**Suggested fix:** Either (a) document that `reset()` must not be called while `scan()` calls are in flight (caller's responsibility, with a docstring warning), or (b) snapshot `self._scanners` into a local variable inside `_ensure_loaded()` and pass it through to `_scan_sync`, so the scan runs against the list that was valid at the time of the check. Option (a) is simpler and sufficient for the intended use case (reset after `pip install`, not during active scanning).

### F-3: `_load_error` check in `scan()` at line 175 is redundant and creates a subtle ordering dependency with `_ensure_loaded()`
**Severity:** P2
**Where:** spec.md:174-176 (scan() flow lines 3-5)
**Edge case:** After `_ensure_loaded()` returns at line 174, `scan()` checks `self._load_error is not None` at line 175. This is logically redundant with the check already inside `_ensure_loaded()` at line 133. However, if `_ensure_loaded()` exits via the `_load_error` fast-path (line 133-134), it returns silently without error. Then `scan()` must read `_load_error` to know what happened. This works, but the control flow is fragile: `_ensure_loaded()` communicates failure via a side-channel (instance state) rather than a return value or exception. If a future maintainer removes the `_load_error` check in `scan()` (believing `_ensure_loaded()` already handles it), all load failures would silently produce empty results with no error message.
**What happens:** Not a bug today, but a maintainability hazard. The dual-check pattern works only if both checks remain synchronized.
**Why the spec misses it:** The split between "check in `_ensure_loaded`" and "check in `scan()`" evolved from the D3b revision but was not explicitly motivated as a two-phase pattern.
**Suggested fix:** Add a brief comment in the spec's `scan()` flow pseudocode: "# _ensure_loaded() returns silently on cached failure; must check _load_error here to report it." Alternatively, have `_ensure_loaded()` return a `str | None` error value that `scan()` consumes directly, removing the side-channel coupling.

### F-4: `_scan_sync` does not re-check `_load_error` inside the thread
**Severity:** P2
**Where:** spec.md:192-211 (_scan_sync code block)
**Edge case:** This is a variant of F-2. If `reset()` is called after `_ensure_loaded()` succeeds (clearing `_loaded` and `_scanners`), `_scan_sync` iterates over an empty list. But there is also the opposite timing: `_scan_sync` begins execution in the thread pool, and between that moment and iteration start, `reset()` runs and clears `_scanners`. Since `_scan_sync` accesses `self._scanners` without any lock, the list could even be mutated mid-iteration (replaced with `[]` by `reset()`), though CPython's GIL makes this specific race practically impossible for list replacement.
**What happens:** Under CPython, this is safe due to GIL atomicity of list assignment. Under alternative Python runtimes (PyPy with STM, free-threaded CPython 3.13+), this could produce undefined behavior.
**Why the spec misses it:** The spec targets Python 3.11+ and CPython, but `pyproject.toml` has `requires-python = ">=3.11"` which does not exclude alternative runtimes.
**Suggested fix:** Document that `reset()` is not thread-safe with respect to concurrent `scan()` calls (same fix as F-2). Alternatively, capture `scanners = self._scanners` at the top of `_scan_sync` to snapshot the reference.

### F-5: `ban_topics` constructor validation does not check for non-string elements
**Severity:** P2
**Where:** spec.md:98-101 (constructor validation)
**Edge case:** `LlmGuardScanner(enable_ban_topics=True, ban_topics=[42, None, ""])` passes the constructor check (`ban_topics` is truthy and non-empty). But LLM Guard's `BanTopics(topics=...)` expects a list of non-empty strings. Passing integers or empty strings would cause a downstream failure inside `_ensure_loaded()`, which would then be cached as a permanent load error, disabling all sub-scanners (not just BanTopics).
**What happens:** Permanent load failure cached. All sub-scanners disabled. The error message from LLM Guard's internal validation may be cryptic and not point back to the `ban_topics` parameter.
**Why the spec misses it:** The validation at line 98 checks `not ban_topics` which catches `None` and `[]` but not lists containing non-string elements or empty strings.
**Suggested fix:** Either (a) validate that all elements are non-empty strings: `if enable_ban_topics and (not ban_topics or not all(isinstance(t, str) and t for t in ban_topics)): raise ValueError(...)`, or (b) document that element-level validation is delegated to LLM Guard with a note that such failures are cached. Option (a) is more robust and produces a clearer error message.

### F-6: Test 12 (thread safety) may not reliably detect the race it targets
**Severity:** P3
**Where:** spec.md:259 (Test 12 description)
**Edge case:** Test 12 spawns 10 concurrent `scan()` calls via `asyncio.gather` and asserts `_ensure_loaded` body executes exactly once. With `asyncio_mode = "auto"` in pytest config, `asyncio.gather` runs all tasks on a single event loop thread. The `asyncio.to_thread` call inside `scan()` dispatches to the default thread pool, but the thread pool's default size is `min(32, os.cpu_count() + 4)`. If the tasks are scheduled sequentially by the event loop before any reach `to_thread`, the first call may complete `_ensure_loaded()` and set `_loaded = True` before others reach it, making the test pass trivially without actually exercising concurrent access.
**What happens:** Test may give false confidence about thread safety. The race condition is real (two asyncio tasks dispatching `to_thread` concurrently), but the test may not reliably reproduce it.
**Why the spec misses it:** The test description assumes `asyncio.gather` implies concurrent execution, but the tasks may be interleaved rather than truly parallel.
**Suggested fix:** Add a note that the test should use `threading.Barrier` or a `threading.Event` inside the mocked `_ensure_loaded` to ensure multiple threads are actually waiting before proceeding. This forces the concurrent access pattern the test intends to verify.

### F-7: `_scan_sync` exception handler swallows exception type information
**Severity:** P3
**Where:** spec.md:209-210 (_scan_sync error handling)
**Edge case:** The error message format is `f"{rule_id}: {exc}"`. For debugging, this loses the exception type. A `TypeError: 'NoneType' object is not iterable` and a `RuntimeError: model corrupted` would both appear as plain strings. When multiple sub-scanners fail with similar messages, the semicolon-delimited error string in `ScanResult.error` becomes difficult to parse.
**What happens:** Degraded debuggability when investigating sub-scanner failures in production logs.
**Why the spec misses it:** The format matches MinimalScanner's `str(exc)` pattern, but MinimalScanner has only a single error path, not N per-sub-scanner errors concatenated.
**Suggested fix:** Change format to `f"{rule_id}: {type(exc).__name__}: {exc}"` to preserve exception type. This is a P3 improvement, not a correctness issue.

### F-8: No test for `reset()` followed by successful re-load
**Severity:** P3
**Where:** spec.md:260 (Test 13 description)
**Edge case:** Test 13 covers `reset()` clearing the cached error and verifying re-attempt. But it does not cover the case where `reset()` is called on a previously *successful* scanner (not a failed one). If someone calls `reset()` on a working scanner, the next `scan()` must re-load successfully. This path exercises `_loaded = False` + `_scanners = []` when `_load_error` is already `None`.
**What happens:** Untested code path. If an implementer introduces a bug in `reset()` that only clears `_loaded` but not `_scanners`, subsequent scans would re-load and append to the existing list, doubling sub-scanner instances.
**Why the spec misses it:** Test 13 focuses on the error-recovery path, which is the primary use case for `reset()`. The "reset a healthy scanner" path is secondary but still reachable.
**Suggested fix:** Add a test case: instantiate scanner, `scan()` successfully (mocked), call `reset()`, `scan()` again, verify `_ensure_loaded` runs again and scanner count is correct (not doubled).

## Summary
P0: 0 | P1: 2 | P2: 3 | P3: 3 | P4: 0

STATUS: RED P0=0 P1=2 P2=3 P3=3 P4=0
