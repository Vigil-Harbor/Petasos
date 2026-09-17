# Conventions Review — round 1

## Closure of round 0 findings
N/A — round 1

## Findings

### F-1: PET-174 allowlist omits the new `MinimalScanner` construction
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md Decision 12 / Helper contract step 4; Scope § Files to change
**Convention violated:** wiki `decisions/2026-08-05-pet-174-one-bootstrap-plus-structural-pin.md` — un-allowlisted scanner construction fails CI; CLAUDE.md “verify load-bearing claims against the actual codebase”
**Evidence:** `tests/test_scanner_bootstrap_structure.py` sweeps `petasos/` and `docs/deployment/` and fails any construction of the four scanner classes outside an exact-match allowlist:

```77:83:tests/test_scanner_bootstrap_structure.py
_ALLOWLIST = frozenset(
    {
        ("petasos/pipeline.py", "Pipeline.__init__"),
        ("docs/deployment/reference_plugin/__init__.py", "_get_fallback_scanner"),
        ("docs/deployment/reference_plugin/verify.py", "check_injection_scan"),
    }
)
```

The same triple is duplicated in `test_allowlist_is_exactly_the_documented_rows`. PET-174: “A legitimate new construction site must be added deliberately and visibly in the same PR — the friction is the feature.” The spec’s private `MinimalScanner(...)` inside `scan_ingestion_result` is a fourth live site and is not named. `tests/test_scanner_bootstrap_structure.py` is absent from Files to change. The shipping suite would fail `test_no_unallowlisted_scanner_construction`.
**Suggested fix:** Add `tests/test_scanner_bootstrap_structure.py` to Files to change. Extend `_ALLOWLIST`, the documented-set assertion, and the per-row reason block with `("petasos/session/ingest.py", "scan_ingestion_result")` and the Decision 12 reason (sweep must not share `pipeline._minimal_scanner`).

### F-2: `_run_ingest_async` breaks the established `_run_async` test harness
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md § Plugin wiring; Scope § Files to change
**Convention violated:** repo harness idiom `_run_async -> asyncio.run` (named in `tests/test_profile_rebind.py`); every handler-driven suite stubs that one submit path
**Evidence:** `_transform_tool_result` today submits via `_run_async`. Tests that drive the handler stub that name:

```330:331:tests/test_ingestion_backstop.py
    monkeypatch.setattr(ref, "_maybe_reconfigure", lambda: None)
    monkeypatch.setattr(ref, "_run_async", lambda coro, timeout=15: asyncio.run(coro))
```

`_drive_shipped_reads` then calls `_transform_tool_result` (line 361). The spec replaces the clip + `_run_async(pipeline.inspect(...))` block with `_run_ingest_async` and does not list `tests/test_ingestion_backstop.py` (77 tests, PET-176 backstop through the real handler). Following the spec, those tests hit a live `petasos-ingest` loop instead of the stub. `test_reference_plugin_tool_result.py` and `test_benchmarks.py` are listed but the spec never says to retarget the stub onto `_run_ingest_async`.
**Suggested fix:** Name `_run_ingest_async` as the new handler submit seam in the test plan. Add `tests/test_ingestion_backstop.py` to Files to change (retarget `_run_async` stubs that sit on `_transform_tool_result`). In the listed suites, say explicitly: handler tests patch `_run_ingest_async`; `_pre_tool_call` tests keep patching `_run_async`.

### F-3: “Duplicate `merge_findings`” hedge fights PET-51 and the existing import graph
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md Helper contract step 6
**Convention violated:** wiki `decisions/2026-05-28-pet-51-severity-first-overlap-resolution.md` (one overlap rule; copies must stay aligned); CLAUDE.md “Reuse vs duplicate” / “Lean on dependencies already in the project”
**Evidence:** The helper already `import`s `Pipeline` from `petasos.pipeline` for `inspect()`. `merge_findings` lives in that same module (`petasos/pipeline.py:144`) and is already imported that way (`tests/test_finding_merge.py`). `ingest.py → pipeline.py` is one-directional; a cycle appears only if `pipeline.py` imported `ingest`, which this spec forbids. PET-51: “Both merge functions must stay aligned on severity-first primary ordering — desynchronizing them would create inconsistent pipeline behavior.” The spec’s “or an equivalent … duplicate the small overlap loop” invites a second copy with no cycle to avoid.
**Suggested fix:** Pin `from petasos.pipeline import Pipeline, merge_findings` and run the existing overlap rule on a synthetic `ScanResult` list. Delete the duplicate-loop hedge. Keep “do not move merge into `_types` / do not refactor `pipeline.py`.”

### F-4: New public export is missing a CHANGELOG **Added** bullet
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md § `CHANGELOG.md` Unreleased
**Convention violated:** Keep a Changelog as used in this repo; PET-170/179/181 recorded new re-exported names under **Added**
**Evidence:** `CHANGELOG.md` Unreleased already has `### Added` for `INGESTION_TOOLS` and `NON_INGESTING_TOOLS`. PET-170 recorded `format_result_notice` as Added (“re-exported from `petasos` and `petasos.session`”). Decision 15 adds `scan_ingestion_result` and `IngestionScanResult` to both `__all__`s — published API. The spec’s CHANGELOG plan has only **Fixed** / **Changed** (plus residuals). CLAUDE.md: public surface changes get a CHANGELOG entry, not a silent addition.
**Suggested fix:** Add an **Added** bullet: `petasos.session.ingest.scan_ingestion_result` / `IngestionScanResult`, re-exported from `petasos` and `petasos.session`; plugin deep-imports the implementing module; `verify.py` probes the name. Keep the gap-closed text under **Fixed** and the layer/isolation text under **Changed**.

### F-5: Sweep skips pipeline profile stages that `inspect()` still applies to the head
**Severity:** P2
**Where:** spec.md Decision 13; Helper contract steps 4–7
**Convention violated:** Silent-addition axis — `Pipeline.inspect()` Stage 4b/5b/5c (`suppress_rules`, `confidence_floor`, `severity_overrides` in `petasos/pipeline.py:777-829`); Decision 13 records the frequency residual but not these siblings
**Evidence:** Today the 8k window is one `inspect()`, so profile suppression and overrides apply. After this spec, the head still goes through `inspect()`; chunks call a private `MinimalScanner(decode_encoded_payloads=...)` with default `suppress_rules=()` and merge without Stage 4b/5b/5c. Floor injection is unsuppressible, so HIGH+ injection still flags; non-floor syntactic families (encoding, homoglyph, RTL, oversized-payload) can reappear on a profile that suppressed or downgraded them. Decision 13 already names the parallel consequence for `FrequencyTracker` / `weight_cap`.
**Suggested fix:** Record next to Decision 13: chunk findings are not filtered by the active profile’s `suppress_rules`, `confidence_floor`, or `severity_overrides`. Either that is the intended residual (banner may fire on a profile-suppressed non-floor rule outside the head), or the helper constructs `MinimalScanner` with the snapshotted profile suppress set and applies the same 5b/5c filters before merge.

### F-6: Author-pinned additions (export, chunk size, ceiling-clean log) are (c), not (d)
**Severity:** P3
**Where:** spec.md Decisions 15–16; § Coverage regimes
**Convention violated:** Silent-additions axis — surface (c) for the human drift-check
**Evidence:** Brief risks 1–2 left export location and chunk payload to the spec author; both pins carry rationale (match `format_result_notice`; 64 KiB stays under `max_payload_bytes` 524_288). Coverage table adds `PETASOS_RESULT_CEILING` (replacing `PETASOS_RESULT_TRUNCATED`) and refuses a third console event type, with PET-170 clean-truncated as prior art. Hex-encoded 8,192-byte blob split is named rather than silently closed.
**Suggested fix:** No design change. Optional: one sentence in Decision 15 that `IngestionCoverage` is not itself in `__all__` (reachable via `IngestionScanResult.coverage`).

### F-7: `inspect_lock` on the published helper is a plugin mutex on the library export
**Severity:** P3
**Where:** spec.md Helper contract signature; Decision 15
**Convention violated:** Premature / cross-surface — `format_result_notice` (the stated analogue) has no host concurrency primitive; `petasos.__all__` is the published API
**Evidence:** Brief placed the mutex in the plugin around `inspect()` (head + parameter scans). The spec puts `inspect_lock: threading.Lock | None` on `scan_ingestion_result`, then re-exports that function from `petasos` and `petasos.session`. Optional `None` keeps tests and playground working; other hosts inherit a threading lock on an async library call.
**Suggested fix:** Keep the parameter (N=1 caller, simplest way to wrap only `inspect()`). In Decision 15, state that `inspect_lock` is host-owned and ignored when `None`, and that it is part of the published signature on purpose so a second host cannot forget the mutex.

### F-8: `_apply_reconfigure` “never yields” invariant is changed without naming PET-126
**Severity:** P3
**Where:** spec.md Decision 12
**Convention violated:** wiki `decisions/2026-06-15-pet-126-reconfigure-primitive-and-failsafe-reload.md` Decision 6 (apply is one loop-serialized unit); plugin docstring at `docs/deployment/reference_plugin/__init__.py:1564-1566`
**Evidence:** Current docstring: “The body is fully synchronous (it never yields), so the steps are atomic with respect to any other loop task.” Decision 12 adds `await asyncio.to_thread(_inspect_lock.acquire)` so apply yields while waiting. The deadlock reason is right; the PET-126 “never yields” sentence and the plugin docstring are not named as edits.
**Suggested fix:** In Decision 12 and Files to change, say `_apply_reconfigure` gains exactly one await (lock acquire); after the lock is held the body stays synchronous. Update the function docstring. Atomicity wrt `inspect()` is now the lock, not “no await in the coroutine.”

### F-9: `verify.py` probe is underspecified against the PET-179 sibling-check pattern
**Severity:** P3
**Where:** spec.md Scope § Files to change; Decision 15
**Convention violated:** PET-179/181 `check_guard_exports` is a sibling `check()` row so an early scanner-imports PASS cannot hide a missing name (`docs/deployment/reference_plugin/verify.py:200-226`)
**Evidence:** Spec says “probe the new export on the existing guard/formatting floor.” `scan_ingestion_result` is not a guard export. A module-scope plugin import already fails `PluginSkewError` on an old library (same as `format_result_notice`). PET-179 still added a named sibling so the FAIL text names the missing symbol.
**Suggested fix:** Pin one of: (a) sibling `check_ingest_export` FAIL-ing on `petasos.session.ingest.scan_ingestion_result`, or (b) rely on plugin-import skew only and say so, matching `format_result_notice` (no dedicated probe today).

## Summary
P0: 0 | P1: 0 | P2: 5 | P3: 4 | P4: 0

STATUS: GREEN
