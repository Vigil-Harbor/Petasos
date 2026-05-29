# Edge-Cases Review -- round 3

## Closure of round 2 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| edge-cases | F-1 | `_load_error` check outside lock but not inside | CLOSED | Spec line 138-139: `if self._load_error is not None: return # another thread failed while we waited for the lock` added inside the `with self._lock:` block, directly after the `_loaded` double-check |
| edge-cases | F-2 | `reset()` during active `scan()` causes silent false-negative | CLOSED | Spec lines 147-154: `reset()` docstring now explicitly warns "Caller must ensure no scan() calls are in flight when calling reset(). Calling reset() during active scanning may produce silent false-negatives... This is the caller's responsibility." D3b decision text (line 59) reinforces: "Safety contract: reset() must not be called while scan() calls are in flight." |
| edge-cases | F-3 | `_load_error` check in `scan()` redundant / side-channel coupling | CLOSED | Spec Deferred section line 346: explicitly acknowledged as P2 deferred: "Control flow relies on side-channel (instance state) rather than return value. Works correctly but is a maintainability hazard." |
| edge-cases | F-4 | `_scan_sync` does not snapshot `_scanners` reference | CLOSED | Spec Deferred section line 347: explicitly acknowledged as P2 deferred: "Under CPython's GIL, list assignment is atomic so reset() cannot corrupt a mid-iteration _scan_sync. Under free-threaded CPython 3.13+ this could theoretically race. Mitigated by reset() caller-responsibility contract." |
| edge-cases | F-5 | `ban_topics` constructor validation does not check element types | CLOSED | Spec Deferred section line 348: explicitly acknowledged as P2 deferred: "ban_topics=[42, None, ''] passes validation but causes downstream LLM Guard failure cached as permanent load error. Future improvement: all(isinstance(t, str) and t for t in ban_topics)." |
| edge-cases | F-6 | Test 12 thread-safety may not reliably detect the race | CLOSED | This was P3 advisory. The test intent is documented and the real protection is the `threading.Lock` in the implementation, not the test's ability to reproduce a race deterministically. Acceptable as-is for a unit test. |
| edge-cases | F-7 | `_scan_sync` exception handler swallows exception type | CLOSED | This was P3 advisory. The spec's error format `f"{rule_id}: {exc}"` is consistent with MinimalScanner's `str(exc)` pattern (minimal.py line 140). While `type(exc).__name__` would improve debuggability, the current approach is consistent and functional. |
| edge-cases | F-8 | No test for `reset()` on a healthy scanner | CLOSED | This was P3 advisory. Test 13 (line 260) covers reset-after-failure which is the primary use case. The `reset()` docstring (lines 147-154) now clarifies it is for maintenance windows only. The risk of a doubled scanner list from a hypothetical bug is low given the `_scanners = []` assignment in `reset()` (line 159) followed by full re-population in `_ensure_loaded()`. |
| correctness | F-1 | `threshold` default 0.85 vs library default 0.92 | N/A | P2 finding from correctness lens; not an edge-case concern. Noted for completeness -- still open as a clarity improvement in the correctness lens. |
| correctness | F-2 | `scanners/__init__.py` adds `MinimalScanner` re-export not in scope | N/A | P2 finding from correctness lens; scope accuracy issue, not an edge-case concern. |
| correctness | F-3 | Done-when "10 scenarios" vs brief "20-message corpus" | N/A | P2 finding from correctness lens; brief-to-spec traceability issue. |
| correctness | F-4 | `Secrets` scanner `risk_score` semantics differ | N/A | P2 finding from correctness lens; documentation/clarity issue. |
| correctness | F-5 | Done-when ">= 20 tests" but test plan lists 24 | N/A | P3 finding from correctness lens; arithmetic clarity issue. |
| correctness | F-6 | Plane ticket not cached in memory | N/A | P3 grounding finding from correctness lens. |
| conventions | F-1 | PET-3/PET-4 disagree on top-level re-export | N/A | P2 finding from conventions lens; cross-spec consistency issue. |
| conventions | F-2 | PET-3/PET-4 incompatible `__init__.py` patterns | N/A | P2 finding from conventions lens; cross-spec consistency issue. |
| conventions | F-3 | `_ensure_loaded` double-state vs PET-4 single-state | N/A | P2 finding from conventions lens; cross-spec consistency issue. |
| conventions | F-4 | `_scanners` is a bare `list[tuple]`, not frozen | N/A | P3 finding from conventions lens; frozen-exports convention. |
| conventions | F-5 | `reset()` is a silent spec addition not in brief | N/A | P3 finding from conventions lens; scope-drift issue. |
| conventions | F-6 | Integration test skip mechanism differs from PET-4 | N/A | P3 finding from conventions lens; cross-spec consistency. |
| conventions | F-7 | `ban_topics` silently ignored without `enable_ban_topics` | N/A | P3 finding from conventions lens; principle-of-least-surprise issue. |

## Findings

All eight edge-cases findings from round 2 are CLOSED. The two P1 fixes (F-1: `_load_error` check inside the lock; F-2: `reset()` caller-responsibility docstring) are clean and do not introduce new edge cases. The remaining six findings (P2 and P3) were either addressed directly or explicitly deferred with rationale.

I have re-probed the following axes against the current spec revision:

**Input edges.** Empty string: documented as passthrough (line 335). Null/missing fields: constructor validates `ban_topics` eagerly (lines 98-101); deferred element-type validation is acknowledged (line 348). Size limits: delegated to pipeline (line 334). Malformed `threshold`: deferred (line 343). All accounted for.

**State and concurrency.** Double-checked locking now checks both `_loaded` and `_load_error` inside the lock (lines 136-139). `reset()` concurrent-use hazard documented in docstring (lines 150-154) and D3b (line 59). `_scanners` snapshot under free-threaded Python deferred with rationale (line 347). All accounted for.

**External-system failures.** Import failure: cached via `_load_error` (lines 133-134, 138-139, 144-145). Model instantiation failure: same path, tested (test 14, line 261). Per-sub-scanner runtime exception: caught per-iteration (lines 204-210), error collected. Outer exception catch-all in `scan()` (line 185). All accounted for.

**Observability.** Error messages include `rule_id` (line 210). `ScanResult.error` aggregates per-scanner errors with semicolons (line 183). Duration tracked via `perf_counter` (line 172). Load error message includes install instructions (D1, line 39). Adequate.

**Test coverage.** Thread safety (test 12), cached failure (test 13), model instantiation failure (test 14), per-scanner error isolation (test 6), clean input (test 15), detection for all five sub-scanners (tests 16-20), confidence mapping (test 21), position/matched_text None (test 22), threshold effect (test 23), direction parameter (test 24). No unhandled edge-case axis lacks a corresponding test.

**Persistence checklist.** This spec introduces no persisted state. `LlmGuardScanner` is a stateless scanner wrapper (in-memory instance state only: `_loaded`, `_load_error`, `_scanners`). No MCP records, no JSON files, no schema columns. N/A.

No findings.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 0 | P4: 0

STATUS: GREEN
