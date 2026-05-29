# PET-49 — PIPE-02: Partial ML Failure in Degraded Mode Passes Content

**Plane:** PET-49 · **Finding:** PIPE-02 · **Priority:** High  
**OWASP:** ASI07 — Insufficient threat-detection coverage  
**Parent:** PET-14 · **Blocks:** PET-12 (release)  
**Status:** Backlog → ready-for-dev  
**Chain:** Part of RT-075 end-to-end

---

## Problem

`_compute_safe` at `petasos/pipeline.py:90–124` evaluates ML scanner health after merging findings. In `degraded` mode (L116–118), only `all_ml_failure` flips `safe` to `False`. When one of two ML scanners errors and the other returns clean, `partial_failure` is `True` but `all_ml_failure` is `False` — so the degraded-mode branch does nothing and `safe` remains `True`.

The concrete attack: an adversary knows one ML scanner is intermittently down (network timeout, model OOM). They send a payload that the downed scanner would catch but the surviving scanner misses (different model coverage). The syntactic pre-filter (MinimalScanner) returns clean because the attack doesn't match any of the 17 regex rules. Result: `safe=True` with only 50% ML defense operational.

The existing test `test_degraded_partial_ml_failure_still_safe` (`tests/adversarial/pipeline/test_degraded_fail_open.py:31–38`) explicitly asserts this behavior — it confirms the bug rather than testing for the fix.

## Prior Art

Drawbridge's TypeScript pipeline (`clawmoat-drawbridge-sanitizer/src/pipeline/index.ts`) does not implement a configurable fail-mode; it always runs all scanners and blocks on any match. The `degraded` / `open` / `closed` tri-state is Petasos-original.

The `closed` mode already handles partial failure correctly at L121–122: `if fail_mode == "closed" and (partial_failure or all_ml_failure): safe = False`. The `degraded` mode simply needs the same `partial_failure` treatment.

Industry precedent: NIST SP 800-53 SI-4 (Information System Monitoring) recommends that partial sensor failure be treated as a degraded-security event, not a pass-through.

## Remediation

### Approach: Treat partial ML outage as unsafe in degraded mode

The `degraded` mode should match `closed` in treating `partial_failure` as unsafe. The distinction between `degraded` and `closed` becomes: `degraded` blocks on partial or total ML failure; `closed` additionally blocks on early-exit for any finding (not just CRITICAL) and treats partial failure identically.

### Changes

**1. `petasos/pipeline.py` — `_compute_safe` L116–118**

Current:

```python
if fail_mode == "degraded":
    if all_ml_failure:
        safe = False
```

Change to:

```python
if fail_mode == "degraded":
    if partial_failure or all_ml_failure:
        safe = False
```

This is a one-line change. Partial ML failure now yields `safe=False` in degraded mode, matching the security posture that "degraded" implies.

**2. `petasos/config.py` — docstring update**

Update the `fail_mode` field docstring to clarify the three modes:

- `open`: ML failures do not affect `safe` (pass-through).
- `degraded`: partial or total ML failure yields `safe=False`; syntactic pre-filter always runs.
- `closed`: same as degraded plus early-exit on CRITICAL from syntactic pre-filter.

### Tests Required

| Test | File | Asserts |
|------|------|---------|
| `test_degraded_partial_ml_failure_blocks` | `tests/adversarial/pipeline/test_degraded_fail_open.py` | Partial ML failure (1 of 2 errored) in degraded mode → `safe=False` |
| `test_degraded_all_ml_failure_blocks` | `tests/adversarial/pipeline/test_degraded_fail_open.py` | All ML scanners errored in degraded mode → `safe=False` (unchanged behavior) |
| `test_degraded_no_ml_failure_passes` | `tests/adversarial/pipeline/test_degraded_fail_open.py` | All ML scanners healthy + clean → `safe=True` |
| `test_degraded_partial_ml_failure_with_findings_blocks` | `tests/adversarial/pipeline/test_degraded_fail_open.py` | Partial ML failure + HIGH/CRITICAL finding from surviving scanner → `safe=False` |
| `test_open_partial_ml_failure_passes` | `tests/adversarial/pipeline/test_degraded_fail_open.py` | `open` mode partial failure → `safe=True` (open mode unaffected) |
| `test_closed_partial_ml_failure_blocks` | `tests/adversarial/pipeline/test_degraded_fail_open.py` | Confirm `closed` still blocks on partial (no regression) |

### What the existing test needs

`test_degraded_partial_ml_failure_still_safe` currently asserts `result.safe is True`. After the fix, rename to `test_degraded_partial_ml_failure_blocks` and assert `result.safe is False`.

## Decisions Carried Forward

- **`degraded` aligns with `closed` on partial failure.** The semantic distinction between the two modes shifts to early-exit behavior (closed exits on any CRITICAL from syntactic pre-filter), not to ML failure tolerance. This is the least surprising interpretation: "degraded" implies reduced capability should mean reduced trust.
- **`open` mode remains unchanged.** Operators who explicitly choose `open` accept the risk of ML failure pass-through. This is intentional for low-risk or debug deployments.
- **No new fail-mode added.** A fourth mode (e.g., `hardened`) was considered but rejected — the tri-state is sufficient when `degraded` properly handles partial failure.
- **Zero-ML-scanner case unchanged.** When `ml_total == 0` (L110–111), the function returns `safe` based on findings alone. This is correct: no ML scanners configured means no ML failure is possible.

## Done When

- [ ] `_compute_safe` treats `partial_failure` as `safe=False` in `degraded` mode
- [ ] `fail_mode` docstring updated in `config.py`
- [ ] Existing test `test_degraded_partial_ml_failure_still_safe` updated to assert `safe=False`
- [ ] All 6 tests listed above pass
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of Scope

- Scanner health monitoring / circuit breaker (separate feature; would require scanner heartbeat)
- Automatic mode escalation (e.g., auto-switch from `open` to `degraded` on repeated ML failures)
- Per-scanner fail-mode (e.g., one scanner can fail-open while another is fail-closed)
- Drawbridge backport (uncoupled; own ticket if needed)
