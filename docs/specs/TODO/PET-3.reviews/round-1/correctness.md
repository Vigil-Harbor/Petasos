# Correctness Review -- round 1

## Closure of round N-1 findings
N/A -- round 1.

## Findings

### F-1: Code block for `_scan_sync` contradicts prose on per-sub-scanner error isolation
**Severity:** P0
**Where:** spec.md:142-159 (section "\_scan\_sync(text) -- runs in thread")
**Claim:** Line 159: "Individual sub-scanner exceptions are caught per-scanner -- a failing Toxicity scanner does not prevent PromptInjection from running. Per-scanner errors are collected and appended to the ScanResult's error field as a semicolon-delimited string."
**Why this is wrong:** The code block at lines 143-156 contains no try/except around the `sub_scanner.scan(text)` call. As written, if any sub-scanner raises, the exception propagates out of the `for` loop, aborting `_scan_sync` entirely. All findings already collected from earlier sub-scanners in that iteration would be lost -- the exception would propagate to `scan()`'s outer `except` handler (line 136-137), which returns `ScanResult(findings=(), error=str(exc))`. The code block says "crash on first sub-scanner failure and lose all findings"; the prose says "isolate failures and keep going." Implementers follow code blocks over prose. This directly contradicts done-when criterion "Per-sub-scanner error isolation verified" (line 236) and test 6 (line 188).
**Suggested fix:** Rewrite the `_scan_sync` code block to include a try/except per iteration.

### F-2: `scan()` flow code block has no path for partial-failure errors to reach `ScanResult.error`
**Severity:** P0
**Where:** spec.md:130-137 (section "scan() flow")
**Claim:** Line 134-135: `findings = await asyncio.to_thread(self._scan_sync, text)` followed by `return ScanResult(scanner_name="llm_guard", findings=tuple(findings), duration_ms=...)`
**Why this is wrong:** The `ScanResult` construction at line 135 does not include an `error=` keyword argument. Even if F-1 is fixed and `_scan_sync` returns collected errors, the `scan()` code block only unpacks `findings` from the `to_thread` call. Per-scanner errors have no plumbing to reach the `ScanResult.error` field. The only `error=` assignment is in the outer `except` block (line 137), which handles total failure -- not partial failure.
**Suggested fix:** Update `scan()` flow code block: `findings, errors = await asyncio.to_thread(self._scan_sync, text)`, then `return ScanResult(..., error="; ".join(errors) if errors else None)`.

### F-3: `enable_ban_topics=True` with `ban_topics=None` causes unspecified failure
**Severity:** P1
**Where:** spec.md:73-84 (class structure), spec.md:99-112 (lazy-load mechanism)
**Claim:** Constructor accepts `enable_ban_topics: bool = False` and `ban_topics: list[str] | None = None` as independent parameters. No guard or default documented.
**Why this is wrong:** LLM Guard's `BanTopics.__init__` requires `topics: list[str]` as a mandatory positional argument. If the wrapper passes `topics=None`, `BanTopics` raises `TypeError`. Because `_ensure_loaded()` sets `self._loaded = True` only at its final line, this failure leaves `_loaded` as `False`, causing every subsequent `scan()` call to retry the failed load, poisoning ALL sub-scanners.
**Suggested fix:** Add an explicit guard: validate at `__init__` time that `enable_ban_topics=True` requires `ban_topics` to be a non-empty list, raising `ValueError` eagerly.

### F-4: "20-message corpus" done-when criterion has no corresponding test
**Severity:** P1
**Where:** spec.md:233 (done-when), spec.md:193-204 (integration test plan)
**Claim:** Done-when: "Integration tests against real `llm-guard` backend (not mocked) with 20-message corpus."
**Why this is wrong:** The test plan lists 10 scenario-based tests, each with a single input message. No test references a corpus, and the total distinct test inputs is approximately 10, not 20.
**Suggested fix:** Either add a corpus-driven integration test or amend the done-when criterion to accurately describe the test strategy.

### F-5: Test command hardcodes `python3.13` instead of using project convention
**Severity:** P2
**Where:** spec.md:216-217
**Claim:** `python3.13 -m pytest tests/test_llm_guard_scanner.py -v`
**Why this is wrong:** The project baselines Python 3.11. CLAUDE.md documents `pytest` without a version prefix. Using `python3.13` could confuse implementers.
**Suggested fix:** Change to `pytest tests/test_llm_guard_scanner.py -v`.

## Summary
P0: 2 | P1: 2 | P2: 1 | P3: 0 | P4: 0

STATUS: RED P0=2 P1=2 P2=1 P3=0 P4=0
