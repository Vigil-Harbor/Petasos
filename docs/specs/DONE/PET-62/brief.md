# PET-62 — SCAN-04: LlamaFirewall Empty Components Masks All-ML-Down

**Plane:** PET-62 · **Finding:** SCAN-04 · **Priority:** High  
**OWASP:** ASI07 — Insufficient AI model and component monitoring  
**Parent:** PET-14 · **Blocks:** PET-12 (release)  
**Status:** refuted (code review) → ready-for-dev

---

## Problem

`LlamaFirewallScanner.scan` at L161–167 of `petasos/scanners/llama_firewall.py` checks `if not self._components` after a successful `_ensure_loaded()` call. When all three components are disabled (`enable_prompt_guard=False`, `enable_alignment_check=False`, `enable_code_shield=False`), the scanner loads successfully (the `llamafirewall` package imports fine), then returns a clean `ScanResult` with no findings and no error:

```python
if not self._components:
    elapsed = (time.perf_counter() - start) * 1000
    return ScanResult(
        scanner_name=self.name,
        findings=(),
        duration_ms=elapsed,
    )
```

This is indistinguishable from a healthy scan that found nothing. The pipeline's fail-mode logic (`degraded`/`closed`) counts this scanner as "up and clean" — it cannot detect that zero ML components actually ran. An operator who configures LlamaFirewall with all components disabled (misconfiguration) or whose components silently fail to register gets a false-clean result that masks the fact that no ML inspection occurred.

The existing test `test_no_components_enabled` (`tests/test_llama_firewall_scanner.py:193–202`) explicitly asserts `r.error is None` for this case — it encodes the current (vulnerable) behavior as correct.

## Prior Art

Drawbridge is TypeScript/npm and does not have a component-level enable/disable pattern — it wraps ClawMoat as a single scanner. No prior art for this specific guard.

The Petasos `LlmGuardScanner` does not have an equivalent issue because it always registers at least one scanner (`PromptInjection`) unconditionally — there is no path to zero scanners after a successful load.

## Remediation

### Approach: Return an error-flagged result when zero components are enabled

The empty-components path should set `error` so the pipeline can distinguish "scanner loaded but inspected nothing" from "scanner loaded and found nothing wrong."

### Changes

**1. `petasos/scanners/llama_firewall.py` — empty-components path (~L161–167)**

Replace the clean return with an error-bearing one:

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

**2. `petasos/scanners/llama_firewall.py` — constructor validation (optional defense-in-depth)**

Add an early warning at `__init__` time. This does not raise (the scanner protocol says "never throw") but logs:

```python
import logging

_logger = logging.getLogger(__name__)

# In __init__, after setting enable flags:
if not any([self._enable_prompt_guard, self._enable_alignment_check,
            self._enable_code_shield]):
    _logger.warning(
        "LlamaFirewallScanner: all components disabled — "
        "scan() will return error, not clean"
    )
```

### Tests Required

| Test | File | Asserts |
|------|------|---------|
| `test_no_components_enabled_returns_error` | `tests/test_llama_firewall_scanner.py` | `r.error is not None` and error message mentions "all components disabled" |
| `test_no_components_enabled_no_findings` | `tests/test_llama_firewall_scanner.py` | `r.findings == ()` (no false findings) |
| `test_single_component_enabled_no_error` | `tests/test_llama_firewall_scanner.py` | Each single-component config returns `r.error is None` on clean scan |
| `test_no_components_duration_tracked` | `tests/test_llama_firewall_scanner.py` | `r.duration_ms > 0` even on the error path |

### What the existing test needs

`test_no_components_enabled` (L193–202) currently asserts `r.error is None`. After the fix, update to assert `r.error is not None` and check the error message content.

## Decisions Carried Forward

- **Error, not exception.** The scanner protocol mandates "pipeline never throws." Returning `error=` in `ScanResult` is the correct signal path — it lets the pipeline's fail-mode logic (`degraded`/`closed`/`open`) decide what to do.
- **Warning at construction, error at scan.** Construction cannot raise, but logging a warning at `__init__` gives operators early feedback in logs. The authoritative signal is the `ScanResult.error` at scan time.
- **No auto-enable of default components.** If an operator explicitly disables all components, that is a misconfiguration to surface, not silently fix. Auto-enabling prompt_guard would mask the operator's intent.

## Done When

- [ ] `scan()` returns `ScanResult(error=...)` when `self._components` is empty after successful load
- [ ] Constructor logs a warning when all components are disabled
- [ ] `test_no_components_enabled` updated to assert error is returned
- [ ] New tests for single-component-enabled paths pass clean
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of Scope

- Pipeline-level aggregation of "how many ML scanners actually ran" (tracked by pipeline orchestration, not individual scanners)
- Dynamic component enable/disable at runtime (components are set at construction)
- Drawbridge backport (Drawbridge is uncoupled; its own ticket if needed)
