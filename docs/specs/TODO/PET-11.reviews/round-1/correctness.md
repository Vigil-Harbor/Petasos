# Correctness Review — round 1

## Closure of round 0 findings
N/A — round 1

## Findings

### F-1: PipelineResult.errors does not contain scanner errors
**Severity:** P0
**Where:** spec.md:134 | spec section 2b. Failure Path, item 4
**Claim:** "**PipelineResult.errors:** Contains error strings from both failed scanners."
**Why this is wrong:** In `petasos/pipeline.py`, scanner errors are caught by `_scan_one()` (lines 127-148) and stored in the individual `ScanResult.error` field, NOT appended to the `errors` list that feeds `PipelineResult.errors`. The `errors` list in `_inspect_inner()` (line 332) only collects exceptions from premium hooks (frequency at line 407, escalation at line 413, audit at line 454, alert at line 460) and anonymization failures (line 435). Scanner-level errors are accessible via `result.scanner_results[i].error` but never propagated to `result.errors`. An implementer writing `assert len(result.errors) >= 2` per this spec would get a failing assertion.
**Suggested fix:** Change the assertion to verify scanner errors via `result.scanner_results`: "Verify that `result.scanner_results` contains ScanResult objects with `error is not None` for both failed mock scanners. `result.errors` may be empty or contain only premium-hook errors."

### F-2: Happy path claims "All features show available" but setup omits tool_guard and profiles
**Severity:** P1
**Where:** spec.md:121 | spec section 2a. Happy Path, item 9
**Claim:** "All features show `\"available\"` in `result.premium_features`."
**Why this is wrong:** The `_build_premium_features()` method in `petasos/pipeline.py` (lines 244-265) checks six features: `frequency`, `escalation`, `profiles`, `tool_guard`, `audit`, `alerting`. The spec's setup (line 107) only enables `frequency_enabled=True, escalation_enabled=True, audit_enabled=True, alert_enabled=True, anonymize=True`. Two features are missing from the setup:
1. `tool_guard_enabled` defaults to `False` in `PetasosConfig` (config.py line 48), so `tool_guard` would show as `"disabled"`, not `"available"`.
2. `profiles` requires `self._default_profile is not None` (pipeline.py line 258-260). The spec's setup does not pass a `profile` argument, so `self._default_profile` would be `None` and `profiles` would show `"disabled"`.
**Suggested fix:** Either (a) add `tool_guard_enabled=True` to the config and pass `profile="standard"` (or any valid profile name) to the Pipeline constructor in the setup, or (b) change the assertion to verify only the four explicitly enabled features show `"available"` and acknowledge that `tool_guard` and `profiles` show `"disabled"`.

### F-3: Happy path anonymization assertion depends on unmentioned presidio installation or redaction_mode override
**Severity:** P1
**Where:** spec.md:120 | spec section 2a. Happy Path, item 8
**Claim:** "**Anonymization:** `sanitized_content` is not None (PII was detected and anonymized)."
**Why this is wrong:** The spec's setup (line 107) sets `anonymize=True` but does not specify `redaction_mode`. The default `redaction_mode` in `PetasosConfig` (config.py line 42) is `"redact"`. In `pipeline.py` (lines 419-435), the anonymization path calls `from petasos.scanners.presidio import anonymize`. The `anonymize()` function dispatches to `_anonymize_engine_path()` for `mode="redact"`, which imports `presidio_analyzer` and `presidio_anonymizer`. If those packages are not installed, an `ImportError` is caught, `errors.append("presidio not installed: anonymization skipped")` is called, and `sanitized_content` remains `None`. The test assertion `sanitized_content is not None` would fail.
**Suggested fix:** Add `redaction_mode="replace"` (or `"mask"`) to the config setup in the happy path E2E test, so anonymization uses the manual path that has no presidio import dependency.

### F-4: Brief done-when criterion "v1.0.0 release candidate tagged" dropped from spec
**Severity:** P1
**Where:** spec.md:302-303 | spec section Out of scope
**Claim:** "**`v1.0.0` tagging.** The brief includes 'v1.0.0 release candidate tagged' as a done-when criterion. This spec treats v1.0.0 tagging as a mechanical step..."
**Why this is wrong:** The brief explicitly lists "v1.0.0 release candidate tagged" as done-when criterion #9 (brief line 105). The spec moves this to "Out of scope" with the rationale that it's a "mechanical step." However, the brief is the requirements document. Dropping a done-when criterion to out-of-scope without the brief being amended constitutes drift.
**Suggested fix:** Either (a) add "v1.0.0 release candidate tagged after all criteria verified" as the final done-when item in the spec, or (b) explicitly document this as a brief override with rationale in a Decision subsection.

### F-5: Plane ticket not cached in MCP memory
**Severity:** P3
N/A — informational.

### F-6: Test file count "20 test files" is inaccurate
**Severity:** P3
**Where:** spec.md:52 | spec section Decision 3
**Claim:** "512 tests collected across 20 test files"
**Why this is wrong:** Only 18 files contain `def test_` functions. `conftest.py` and `__init__.py` do not.
**Suggested fix:** Change "20 test files" to "18 test files".

### F-7: Benchmark code block uses `valid_key` as bare variable, not fixture argument
**Severity:** P2
**Where:** spec.md:194 | spec section 3c. Full Pipeline
**Suggested fix:** Update the function signature to `def test_benchmark_full_pipeline(benchmark, valid_key)`.

### F-8: MockMLScanner name collision when two instances used in failure path
**Severity:** P2
**Where:** spec.md:149 | spec section Mock Scanner Implementation
**Suggested fix:** Parameterize the mock scanner name.

## Summary
P0: 1 | P1: 3 | P2: 2 | P3: 2 | P4: 0

STATUS: RED P0=1 P1=3 P2=2 P3=2 P4=0
