# Reconciliation Report: PET-60

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-60.spec.md
> Merge: PR #39 (06e58c2)
> Plane state: Done (group: completed)

## Summary
All five source-code decisions (SCAN-02 confidence clamp, SCAN-06 overlap alignment, SYN-04 NUL/DEL, SYN-05 string-aware JSON depth, SYN-07 syntactic-error propagation) shipped exactly as specced and are confirmed on disk. Drift is confined to test coverage and documentation: the SCAN-02 unit tests (spec test plan #1-4, #3b, #16) were never written, and the `anonymize()` docstring update (a Done-when criterion) was not made.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/scanners/minimal.py` | Yes | SYN-04 `_BINARY_PATTERN` extended; SYN-05 `_check_json_depth()` rewritten as state machine. Matches spec verbatim. |
| `petasos/scanners/llm_guard.py` | Yes | SCAN-02 inline clamp + `import math` at L174-176. |
| `petasos/scanners/presidio.py` | Yes | SCAN-02 clamp L183; SCAN-06 `_resolve_overlaps()` severity-first tiebreaker L217-221; local `_SEVERITY_RANK` added. `anonymize()` docstring NOT updated (see AC #5). |
| `petasos/scanners/llama_firewall.py` | Yes | SCAN-02 `math.isfinite` guard added to existing clamp L133-135. |
| `petasos/pipeline.py` | Yes | SYN-07 `syntactic_error` flag + check before `ml_total == 0` early return, L118-133. |
| `tests/test_minimal_scanner.py` | Yes | `TestBinaryPattern` + `TestJsonDepth` classes added (SYN-04/SYN-05). |
| `tests/test_pipeline.py` | Yes | `TestMinimalScannerError` class added (SYN-07). |
| `tests/adversarial/syntactic/test_injection_evasion.py` | Yes | Both tests renamed and flipped to assert fixed behavior. |
| `tests/adversarial/syntactic/test_binary_nul.py` | Yes | New, single adversarial test. |
| `tests/adversarial/syntactic/test_json_depth_strings.py` | Yes | New, single adversarial test. |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-60.test-output.txt` — captured pytest run log (artifact added by ship-spec flow; harmless).

Spec-named test files NOT touched (Dropped test coverage):
- `tests/test_llm_guard_scanner.py` — spec test plan #1-3 (`test_confidence_clamped_high/negative/nan`) were never added.
- `tests/test_presidio_scanner.py` — spec test plan #4 (`test_presidio_confidence_clamped`) and #16 (`test_overlap_resolve_severity_first`) were never added.
- `tests/test_llama_firewall_scanner.py` — spec test plan #3b (`test_llama_confidence_nan`) was never added. (A pre-existing `test_confidence_clamped_high` from PET-4 exists but does not cover the NaN guard.)

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | SCAN-02 inline confidence clamp with `math.isfinite()` NaN guard in all 3 ML scanners | Confirmed | `llm_guard.py:174-176`, `presidio.py:183`, `llama_firewall.py:133-135`; `import math` present in each |
| D2 | SCAN-06 `_resolve_overlaps()` tiebreaker aligned to severity-first-then-confidence; local `_SEVERITY_RANK` | Confirmed | `presidio.py:217-221` (severity-first), `presidio.py:40-47` (local `_SEVERITY_RANK` dict, not imported from pipeline) |
| D3 | SYN-04 extend `_BINARY_PATTERN` to `[\x00-\x08\x0e-\x1f\x7f]` | Confirmed | `minimal.py:58` matches spec exactly |
| D4 | SYN-05 string-aware `_check_json_depth()` state machine | Confirmed | `minimal.py:223-240` — `in_string`/`prev_backslash` toggle matches spec code block verbatim |
| D5 | SYN-07 `syntactic_error` flag checked before `ml_total == 0` early return | Confirmed | `pipeline.py:118-133` — flag set in minimal branch, checked at L130 before L133 early return |
| D6 | Flip + rename two existing adversarial tests | Confirmed | `test_injection_evasion.py`: `test_nul_byte_flagged_by_binary_pattern` asserts `any(...)`; `test_json_depth_skips_brackets_inside_strings` asserts `depth == 1` |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | LlmGuard raw 99.0 -> confidence 1.0 | Met (code) | `llm_guard.py:174-176` clamps via `min(1.0, ...)`. No dedicated test (see Test Plan #1). |
| 2 | LlmGuard `nan` -> confidence 0.0 | Met (code) | `llm_guard.py:174-176` `math.isfinite` guard -> 0.0. No dedicated test. |
| 3 | Presidio raw 1.5 -> confidence 1.0 | Met (code) | `presidio.py:183` `min(1.0, ...)`. No dedicated test (#4). |
| 4 | `_resolve_overlaps()` severity-first tiebreaker | Met | `presidio.py:217-221` |
| 5 | `anonymize()` docstring documents pre-merged expectation | Unmet | `presidio.py:228-248` — `anonymize()` has NO docstring at all; the pre-merge note was never added |
| 6 | `\x00` triggers `binary-content` | Met | `minimal.py:58`; `test_binary_nul_byte_detected` passes |
| 7 | `\x7f` triggers `binary-content` | Met | `minimal.py:58`; `test_binary_del_byte_detected` passes |
| 8 | `_check_json_depth('{"key": "[[["}')` returns 1 | Met | `test_json_depth_string_literal_brackets` passes (asserts `== 1`) |
| 9 | Handles escaped quotes + consecutive backslashes | Met | `test_json_depth_escaped_quote`, `test_json_depth_consecutive_backslash` pass |
| 10 | MinimalScanner error in `degraded` -> safe=False (even with 0 ML scanners) | Met | `pipeline.py:130` before L133 early return; `test_minimal_error_degraded_unsafe` passes |
| 11 | MinimalScanner error in `open` -> not forced unsafe | Met | `pipeline.py:130` excludes `open`; `test_minimal_error_open_passthrough` passes |
| 12 | Existing adversarial tests flipped | Met | `test_injection_evasion.py` both flipped (D6) |
| 13 | All 20 tests listed pass | Unmet | Tests #1-4, #3b, #16 (SCAN-02 unit + overlap-severity tests) do not exist; the 14 SYN-04/05/07 + adversarial tests that do exist pass (33 collected) |
| 14 | `ruff check .` and `mypy --strict .` clean | Unverifiable | Not re-run in this read-only reconciliation; review round-3 STATUS GREEN suggests clean at merge |
| 15 | No regression in full `pytest` suite | Unverifiable | Full suite not re-run here; named PET-60 subset passes (33 passed) |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| #1 `test_confidence_clamped_high` (llm_guard) | No | not in `tests/test_llm_guard_scanner.py` (only pre-existing `test_confidence_is_float_in_range` L418) |
| #2 `test_confidence_clamped_negative` (llm_guard) | No | absent |
| #3 `test_confidence_clamped_nan` (llm_guard) | No | absent |
| #3b `test_llama_confidence_nan` (llama) | No | absent (pre-existing `test_confidence_clamped_high` from PET-4 does not cover NaN) |
| #4 `test_presidio_confidence_clamped` | No | absent from `tests/test_presidio_scanner.py` |
| #5 `test_binary_nul_byte_detected` | Yes | `tests/test_minimal_scanner.py` (TestBinaryPattern) |
| #6 `test_binary_del_byte_detected` | Yes | `tests/test_minimal_scanner.py` |
| #7 `test_binary_tab_not_flagged` | Yes | `tests/test_minimal_scanner.py` |
| #8 `test_json_depth_string_literal_brackets` | Yes | `tests/test_minimal_scanner.py` (TestJsonDepth) |
| #9 `test_json_depth_escaped_quote` | Yes | `tests/test_minimal_scanner.py` |
| #10 `test_json_depth_consecutive_backslash` | Yes | `tests/test_minimal_scanner.py` |
| #11 `test_json_depth_nested_objects` | Yes | `tests/test_minimal_scanner.py` |
| #12 `test_json_depth_no_brackets` | Yes | `tests/test_minimal_scanner.py` |
| #12b `test_json_depth_unmatched_quote` | Yes | `tests/test_minimal_scanner.py` |
| #13 `test_minimal_error_degraded_unsafe` | Yes | `tests/test_pipeline.py` (TestMinimalScannerError) |
| #14 `test_minimal_error_open_passthrough` | Yes | `tests/test_pipeline.py` |
| #15 `test_minimal_error_closed_unsafe` | Yes | `tests/test_pipeline.py` |
| #16 `test_overlap_resolve_severity_first` (presidio) | No | absent; existing `test_overlapping_higher_confidence_wins` L325 is confidence-only, predates and does not cover severity-first |
| #17 `test_nul_byte_in_injection_payload` | Yes | `tests/adversarial/syntactic/test_binary_nul.py` |
| #18 `test_json_depth_brackets_in_string` | Yes | `tests/adversarial/syntactic/test_json_depth_strings.py` |
| #19 flip `test_nul_byte_*_by_binary_pattern` | Yes | `tests/adversarial/syntactic/test_injection_evasion.py` (renamed `_flagged_`) |
| #20 flip `test_json_depth_*_inside_strings` | Yes | `tests/adversarial/syntactic/test_injection_evasion.py` (renamed `_skips_`, asserts `== 1`) |

## Wiki-ready
- SCAN-02 NaN fail-safe direction: `max(0.0, min(1.0, NaN))` returns `1.0` in CPython (unordered NaN comparison lets the first arg win), which would inflate a non-finite confidence to maximum risk. The `math.isfinite()` guard mapping NaN/inf/-inf to `0.0` is the correct fail-safe and is now the established pattern across all three ML scanner wrappers — reusable and constraining for future scanner backends.
- SCAN-06 deliberate divergence: `_resolve_overlaps()` aligns its *primary* tiebreaker with `merge_findings()` (severity-first) but intentionally keeps only the first finding on equal severity+confidence, where `merge_findings()` keeps both — because double-redaction of an overlapping span garbles anonymized output. Non-obvious constraint worth recording.

RECONCILED: no DRIFT: 4
