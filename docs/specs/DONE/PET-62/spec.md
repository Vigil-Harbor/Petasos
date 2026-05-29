# PET-62 — SCAN-04: LlamaFirewall Empty Components Returns Error

**Ticket:** PET-62 · **Finding:** SCAN-04 · **Priority:** High
**Parent:** PET-14 · **Blocks:** PET-12 (release)

## Goal

When `LlamaFirewallScanner` is configured with all three components disabled (`enable_prompt_guard=False`, `enable_alignment_check=False`, `enable_code_shield=False`), `scan()` currently returns a clean `ScanResult` with no error. This is indistinguishable from a healthy scan that found nothing. The pipeline's `_compute_safe` logic skips this scanner entirely (it counts as a non-errored ML scanner), masking the fact that zero ML components actually ran. This change makes the empty-components path return `ScanResult(error=...)` so the pipeline can detect the misconfiguration through its existing fail-mode logic.

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/scanners/llama_firewall.py` | Add error string to empty-components return; add `__init__` warning log |
| `tests/test_llama_firewall_scanner.py` | Update `test_no_components_enabled` assertion; add new tests |

### Files to leave alone

- `petasos/pipeline.py` — no changes needed; `_compute_safe` already handles `r.error is not None` correctly
- `petasos/_types.py` — `ScanResult.error` field already exists
- Other scanner backends — `LlmGuardScanner` unconditionally registers `PromptInjection`; `PresidioScanner` has its own load path; neither has a zero-component path

## Design

### D1: Error string on empty-components path

At `llama_firewall.py` L161–167, the `if not self._components` branch currently returns a clean `ScanResult` with no error field. Replace it with an error-bearing return:

```python
if not self._components:
    elapsed = (time.perf_counter() - start) * 1000
    return ScanResult(
        scanner_name=self.name,
        findings=(),
        duration_ms=elapsed,
        error="all components disabled — no ML inspection performed",
    )
```

**Rationale:** The scanner protocol says "pipeline never throws." Returning `error=` in `ScanResult` is the correct signal path. The pipeline's `_compute_safe` already counts any scanner with `r.error is not None` as an errored ML scanner. When this is the only ML scanner, `all_ml_failure` becomes true and `degraded` mode marks content unsafe.

### D2: Warning log when load succeeds but zero components are enabled

Add a `logging.getLogger(__name__)` logger and emit a warning inside `_ensure_loaded()` when the load succeeds but `self._components` is empty. This defers the warning until the package is confirmed importable — a constructor-time warning would fire even when `llamafirewall` isn't installed, producing a misleading "all components disabled" message when the real problem is a missing dependency.

```python
import logging

_logger = logging.getLogger(__name__)

# Inside _ensure_loaded(), after the for-loop that populates self._components:
if not self._components:
    _logger.warning(
        "LlamaFirewallScanner: all components disabled — "
        "scan() will return error, not clean"
    )
```

**Rationale:** Construction cannot raise (scanner protocol). Deferring to `_ensure_loaded()` avoids a misleading log when the package isn't installed. The warning fires exactly once (guarded by `self._loaded`). The authoritative signal remains the `ScanResult.error` at scan time.

### D3: No auto-enable of default components

If an operator explicitly disables all components, that is a misconfiguration to surface, not silently fix. Auto-enabling `prompt_guard` would mask the operator's intent.

### D4: Existing test update

`test_no_components_enabled` (L193–202) currently asserts `r.error is None`. After the fix, this test must assert `r.error is not None` and verify the error message contains "all components disabled". The `r.findings == ()` assertion stays — the scanner should not fabricate findings, only report the error.

## Test plan

| # | Test | File | Asserts |
|---|------|------|---------|
| 1 | `test_no_components_enabled` (update) | `tests/test_llama_firewall_scanner.py` | `r.error is not None`, `"all components disabled" in r.error`, `r.findings == ()` |
| 2 | `test_no_components_duration_tracked` | `tests/test_llama_firewall_scanner.py` | `r.duration_ms > 0` on the error path |
| 3 | `test_single_component_enabled_no_error` | `tests/test_llama_firewall_scanner.py` | Each single-component config (`prompt_guard`, `alignment_check`, `code_shield` individually) returns `r.error is None` on a clean scan |
| 4 | `test_all_disabled_warns_on_load` | `tests/test_llama_firewall_scanner.py` | Warning log emitted on first `scan()` (inside `_ensure_loaded`) when all components disabled |

All tests use `_injected_mock()` and belong in the `TestUnit` class, ensuring they run without the real `llamafirewall` backend.

### Regression guard

Test 1 is the direct regression for SCAN-04 — it inverts the previous assertion that encoded the vulnerable behavior as correct.

## Test command

```
python -m pytest tests/test_llama_firewall_scanner.py -v
```

## Done when

- [ ] `scan()` returns `ScanResult(error=...)` when `self._components` is empty after successful load
- [ ] Constructor logs a warning when all components are disabled
- [ ] `test_no_components_enabled` updated to assert error is returned
- [ ] New tests for single-component-enabled paths pass clean
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of scope

- Pipeline-level aggregation of "how many ML scanners actually ran" (tracked by pipeline orchestration, not individual scanners)
- Dynamic component enable/disable at runtime (components are set at construction)
- Drawbridge backport (Drawbridge is uncoupled; its own ticket if needed)
