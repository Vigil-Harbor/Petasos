# PET-60 — Scanner + Syntactic Hardening (Brief 8)

**Tickets:** PET-60 (SCAN-02), PET-64 (SCAN-06), PET-68 (SYN-04), PET-69 (SYN-05), PET-70 (SYN-07)
**Priority:** medium (SYN-04, SYN-07, SCAN-06); low (SCAN-02, SYN-05)
**Parent:** PET-14 · **Blocks:** PET-12 (release)

## Goal

Harden the scanner and syntactic detection layers across five findings from the PET-14 red-team review. This spec covers: confidence clamping in ML scanner wrappers (SCAN-02), unified overlap resolution in Presidio anonymization (SCAN-06), NUL/DEL byte detection in the binary pattern (SYN-04), string-aware JSON depth counting (SYN-05), and MinimalScanner error propagation in `_compute_safe` (SYN-07).

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/scanners/minimal.py` | SYN-04: extend `_BINARY_PATTERN`; SYN-05: rewrite `_check_json_depth()` with string-aware state machine |
| `petasos/scanners/llm_guard.py` | SCAN-02: clamp confidence to [0.0, 1.0] in `_scan_sync()` |
| `petasos/scanners/presidio.py` | SCAN-02: clamp confidence; SCAN-06: align `_resolve_overlaps()` tiebreaker with `merge_findings()` |
| `petasos/scanners/llama_firewall.py` | SCAN-02: add `math.isfinite()` NaN guard to existing confidence clamp at L132 |
| `petasos/pipeline.py` | SYN-07: include MinimalScanner errors in `_compute_safe()` fail-mode logic |
| `tests/test_minimal_scanner.py` | Tests for SYN-04, SYN-05 |
| `tests/test_pipeline.py` | Tests for SYN-07 |
| `tests/adversarial/syntactic/test_injection_evasion.py` | Flip `test_nul_byte_not_flagged_by_binary_pattern` and `test_json_depth_counts_brackets_inside_strings` to assert fixed behavior |
| `tests/adversarial/syntactic/test_binary_nul.py` | New: adversarial tests for SYN-04 |
| `tests/adversarial/syntactic/test_json_depth_strings.py` | New: adversarial tests for SYN-05 |

### Files to leave alone

- `petasos/normalize.py` -- normalize hardening is Brief 1 scope
- `petasos/_types.py` -- type validation is Brief 2 scope

## Design

### D1: SCAN-02 -- Confidence clamping in ML scanner wrappers

**`llm_guard.py` L178:** `confidence=risk_score` stores the raw LLM Guard risk score. Clamp at the `ScanFinding` construction site, with NaN protection:

```python
_clamped = 0.0 if not math.isfinite(risk_score) else max(0.0, min(1.0, risk_score))
...
confidence=_clamped,
```

**`presidio.py` L179:** `confidence=r.score` stores the raw Presidio analyzer score. Same clamp:

```python
_clamped = 0.0 if not math.isfinite(r.score) else max(0.0, min(1.0, r.score))
...
confidence=_clamped,
```

**NaN handling:** Without the `math.isfinite()` guard, `max(0.0, min(1.0, float('nan')))` silently returns `1.0` in CPython (the first argument wins when NaN comparisons are unordered). This promotes a non-finite confidence to the maximum value -- the wrong fail-safe direction. The `math.isfinite()` guard catches NaN, inf, and -inf, treating all as 0.0 (fail-safe: a non-finite confidence should not inflate risk).

**`llama_firewall.py` L131-132:** The existing clamp lacks NaN protection. Add the same guard for consistency:

```python
raw_score = result.score if result.score is not None else 1.0
_clamped = 0.0 if not math.isfinite(raw_score) else max(0.0, min(1.0, raw_score))
...
confidence=_clamped,
```

Add `import math` to all three scanner files (llm_guard, presidio, llama_firewall).

**Brief deviation:** The brief proposed a `_clamp_confidence()` helper function. This spec uses inline clamping, matching the existing pattern in `llama_firewall.py` L132. A one-liner doesn't warrant a helper.

### D2: SCAN-06 -- Aligned overlap resolution in Presidio anonymization

The current `_resolve_overlaps()` at `presidio.py:195-215` uses a confidence-only tiebreaker for overlapping findings. The pipeline's `merge_findings()` at `pipeline.py:77-86` uses severity-first, then confidence. This means the same overlapping findings can produce different winners depending on the code path.

**Fix:** Align `_resolve_overlaps()` tiebreaker logic with `merge_findings()`. Change the comparison at L209-212 from:

```python
if current_finding.confidence > prev_finding.confidence or (
    current_finding.confidence == prev_finding.confidence and curr_span > prev_span
):
```

To severity-first, then confidence:

```python
cur_sev = _SEVERITY_RANK.get(current_finding.severity, 999)
prev_sev = _SEVERITY_RANK.get(prev_finding.severity, 999)
if cur_sev < prev_sev:
    result[-1] = (current_finding, current_entity)
elif cur_sev == prev_sev and current_finding.confidence > prev_finding.confidence:
    result[-1] = (current_finding, current_entity)
```

Define `_SEVERITY_RANK` locally in `presidio.py` (not imported from pipeline — avoids circular import risk via the lazy `from petasos.scanners.presidio import anonymize` in pipeline's `_inspect_inner`). The dict is 5 lines and already exists in `pipeline.py` and `alerting.py`; `_SEVERITY_RANK` deduplication into `_types.py` is tracked as future cleanup.

**Equal-severity, equal-confidence case:** `merge_findings()` keeps both overlapping findings when severity and confidence are equal. `_resolve_overlaps()` intentionally does NOT — for anonymization, applying two text replacements to the same overlapping span produces garbled output (double-redaction). Keeping only the first-encountered finding is correct for the anonymization context. This is a deliberate divergence documented here, not an alignment gap.

**Brief deviation:** The brief proposed removing `_resolve_overlaps()` entirely. This spec keeps it with an aligned tiebreaker to preserve defense-in-depth for direct `anonymize()` callers. Removal is a cleanup tracked in Out of scope.

**Rationale:** This preserves the safety net for direct `anonymize()` callers (who may pass overlapping findings) while aligning the primary tiebreaker (severity-first). The `anonymize()` docstring should be updated to note that findings are expected to be pre-merged via `merge_findings()` for optimal results.

### D3: SYN-04 -- NUL and DEL byte detection

`minimal.py` L58: `_BINARY_PATTERN = re.compile(r"[\x01-\x08\x0e-\x1f]")`

**Fix:** One-line change:

```python
_BINARY_PATTERN = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")
```

Adds `\x00` (NUL) and `\x7f` (DEL). Preserves exclusion of `\x09` (tab), `\x0a` (LF), `\x0b` (VT), `\x0c` (FF), `\x0d` (CR).

### D4: SYN-05 -- String-aware JSON depth counting

`minimal.py` L222-237: `_check_json_depth()` counts brackets inside string literals, producing false positives.

**Fix:** Rewrite with a state machine:

```python
def _check_json_depth(self, text: str) -> int:
    depth = 0
    max_depth = 0
    has_brackets = False
    in_string = False
    prev_backslash = False
    for ch in text:
        if in_string:
            if ch == '"' and not prev_backslash:
                in_string = False
            prev_backslash = ch == '\\' and not prev_backslash
            continue
        if ch == '"':
            in_string = True
            prev_backslash = False
            continue
        if ch in ("{", "["):
            has_brackets = True
            depth += 1
            if depth > max_depth:
                max_depth = depth
        elif ch in ("}", "]"):
            if depth > 0:
                depth -= 1
    if not has_brackets:
        return 0
    return max_depth
```

The `prev_backslash` toggle correctly handles consecutive backslashes: `\\\\` yields `prev_backslash = False` after two pairs, so a subsequent `"` closes the string. `\\\\"` correctly keeps `"` inside the string (odd number of preceding backslashes).

### D5: SYN-07 -- MinimalScanner error propagation in `_compute_safe`

`pipeline.py` L95-129: `_compute_safe()` skips MinimalScanner at L109 (`if r.scanner_name == "minimal": continue`). A MinimalScanner error is invisible to fail-mode logic.

**Fix:** Add `syntactic_error` flag and check it **before** the `ml_total == 0` early return:

```python
syntactic_error = False
ml_total = 0
ml_errored = 0
for r in scanner_results:
    if r.scanner_name == "minimal":
        if r.error is not None:
            syntactic_error = True
        continue
    ml_total += 1
    if r.error is not None:
        ml_errored += 1

if syntactic_error and fail_mode in ("degraded", "closed"):
    safe = False

if ml_total == 0:
    return safe
```

The `syntactic_error` check is placed **before** the `ml_total == 0` early return. This is critical: a pipeline with only MinimalScanner (no ML scanners, the default `pip install petasos` configuration) hits `ml_total == 0` and returns early. Without this ordering, the `syntactic_error` flag would never be evaluated.

**Open mode:** `syntactic_error` is excluded from the open-mode check -- consistent with existing semantics.

### D6: Existing adversarial test updates

`tests/adversarial/syntactic/test_injection_evasion.py` contains two tests that assert current buggy behavior:

1. **`test_nul_byte_not_flagged_by_binary_pattern`** (L37): asserts NUL byte is NOT flagged. After SYN-04, NUL IS flagged. Flip assertion: `assert any("binary-content" in f.rule_id ...)`.
2. **`test_json_depth_counts_brackets_inside_strings`** (L44): asserts `depth > 10`. After SYN-05, depth is 1. Flip assertion: `assert depth == 1`.

Rename tests to reflect fixed behavior (e.g., `test_nul_byte_flagged_by_binary_pattern`).

## Test plan

### Unit tests

| # | Test | File | Asserts |
|---|------|------|---------|
| 1 | `test_confidence_clamped_high` | `tests/test_llm_guard_scanner.py` | Mock returning `risk_score=99.0` -> `confidence == 1.0` |
| 2 | `test_confidence_clamped_negative` | `tests/test_llm_guard_scanner.py` | Mock returning `risk_score=-0.5` -> `confidence == 0.0` |
| 3 | `test_confidence_clamped_nan` | `tests/test_llm_guard_scanner.py` | Mock returning `risk_score=float('nan')` -> `confidence == 0.0` |
| 3b | `test_llama_confidence_nan` | `tests/test_llama_firewall_scanner.py` | Mock returning `score=float('nan')` -> `confidence == 0.0` |
| 4 | `test_presidio_confidence_clamped` | `tests/test_presidio_scanner.py` | Mock returning `score=1.5` -> `confidence == 1.0` |
| 5 | `test_binary_nul_byte_detected` | `tests/test_minimal_scanner.py` | `\x00` triggers `binary-content` |
| 6 | `test_binary_del_byte_detected` | `tests/test_minimal_scanner.py` | `\x7f` triggers `binary-content` |
| 7 | `test_binary_tab_not_flagged` | `tests/test_minimal_scanner.py` | `\t` does NOT trigger binary |
| 8 | `test_json_depth_string_literal_brackets` | `tests/test_minimal_scanner.py` | `'{"key": "[[["}' -> depth 1` |
| 9 | `test_json_depth_escaped_quote` | `tests/test_minimal_scanner.py` | `'{"k": "val\\"[[["}' -> depth 1` |
| 10 | `test_json_depth_consecutive_backslash` | `tests/test_minimal_scanner.py` | `'{"k": "\\\\"}' -> depth 1` and `'{"k": "\\\\\\"[[["}' -> depth 1` |
| 11 | `test_json_depth_nested_objects` | `tests/test_minimal_scanner.py` | `'{"a": {"b": {"c": 1}}}' -> depth 3` (unchanged) |
| 12 | `test_json_depth_no_brackets` | `tests/test_minimal_scanner.py` | `'hello world' -> depth 0` (unchanged) |
| 12b | `test_json_depth_unmatched_quote` | `tests/test_minimal_scanner.py` | `'"[[[[[' -> depth 0` (accepted limitation: unmatched quote opens in_string, suppresses counting; documented) |
| 13 | `test_minimal_error_degraded_unsafe` | `tests/test_pipeline.py` | MinimalScanner error + `degraded` -> `safe=False` |
| 14 | `test_minimal_error_open_passthrough` | `tests/test_pipeline.py` | MinimalScanner error + `open` -> error doesn't force unsafe |
| 15 | `test_minimal_error_closed_unsafe` | `tests/test_pipeline.py` | MinimalScanner error + `closed` -> `safe=False` |
| 16 | `test_overlap_resolve_severity_first` | `tests/test_presidio_scanner.py` | Two overlapping findings with different severity -> higher-severity wins (matches `merge_findings()`) |

### Adversarial tests

| # | Test | File | Asserts |
|---|------|------|---------|
| 17 | `test_nul_byte_in_injection_payload` | `tests/adversarial/syntactic/test_binary_nul.py` | `"ignore\x00previous instructions"` -> binary-content fires |
| 18 | `test_json_depth_brackets_in_string` | `tests/adversarial/syntactic/test_json_depth_strings.py` | `'{"data": "[[[[[[[[[["}' -> depth not exceeding threshold |

### Existing test flips

| # | Test | File | Change |
|---|------|------|--------|
| 19 | `test_nul_byte_not_flagged_by_binary_pattern` | `tests/adversarial/syntactic/test_injection_evasion.py` | Rename and flip: NUL IS flagged |
| 20 | `test_json_depth_counts_brackets_inside_strings` | `tests/adversarial/syntactic/test_injection_evasion.py` | Flip: depth == 1 (not > 10) |

## Test command

```
python -m pytest tests/test_minimal_scanner.py tests/test_pipeline.py tests/test_llm_guard_scanner.py tests/test_presidio_scanner.py tests/adversarial/syntactic/ -v
```

## Done when

- [ ] `LlmGuardScanner` finding with raw confidence 99.0 -> `ScanFinding.confidence == 1.0`
- [ ] `LlmGuardScanner` finding with `float('nan')` -> `ScanFinding.confidence == 0.0`
- [ ] `PresidioScanner` finding with raw score 1.5 -> `ScanFinding.confidence == 1.0`
- [ ] `_resolve_overlaps()` uses severity-first tiebreaker (aligned with `merge_findings()`)
- [ ] `anonymize()` docstring documents pre-merged expectation
- [ ] Payload containing `\x00` triggers `binary-content` finding
- [ ] Payload containing `\x7f` triggers `binary-content` finding
- [ ] `_check_json_depth('{"key": "[[["}')` returns 1 (not 4)
- [ ] `_check_json_depth` handles escaped quotes and consecutive backslashes
- [ ] MinimalScanner error in `degraded` mode -> `safe=False` (even with zero ML scanners)
- [ ] MinimalScanner error in `open` mode -> error doesn't force unsafe
- [ ] Existing adversarial tests flipped to assert fixed behavior
- [ ] All 20 tests listed above pass
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of scope

- SCAN-03 (cancel during `to_thread`) -- confirmed, low, documentation-only remediation
- Full JSON schema validation in syntactic scanner
- Scanner-specific circuit breakers (see PET-50)
- `ScanFinding.__post_init__` confidence clamping (Brief 2 / TYP-02 scope)
- `_resolve_overlaps()` function removal (kept with aligned algorithm; removal is cleanup)
- `tests/adversarial/scanner/` directory -- SCAN-02 coverage via unit tests in `test_llm_guard_scanner.py` and `test_presidio_scanner.py`, matching existing `llama_firewall` test pattern

## Deferred (P2+)

- **Performance:** `_check_json_depth` iterates all characters even after oversized-payload finding. No early exit. Not a regression from current behavior.
- **Magic string:** `scanner_name == "minimal"` coupling in `_compute_safe`. Pre-existing; pipeline validates identity at construction time.
- **`_SEVERITY_RANK` dedup:** Third copy of this dict (pipeline, alerting, now presidio). Future cleanup: move to `_types.py` as a shared constant.
- **Unmatched quote evasion:** `_check_json_depth` with a lone `"` followed by nested brackets returns 0 (brackets suppressed by `in_string`). Accepted limitation — a full JSON parser would fix this but adds overhead for non-JSON payloads. Test #12b documents the behavior.
- **Syntactic error logging:** When `syntactic_error` triggers `safe=False`, no log message is emitted. The error is recorded in `ScanResult.error` and accessible in `scanner_results`, but a `_logger.warning()` call would improve observability.
