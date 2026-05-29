# PET-49 — PIPE-02: Partial ML Failure Blocks in Degraded Mode

**Ticket:** PET-49 · **Finding:** PIPE-02 · **Priority:** High
**Parent:** PET-14 · **Blocks:** PET-12 (release)
**Chain:** RT-075 link 3

---

## Goal

Make `degraded` fail-mode treat partial ML scanner failure the same as total ML failure: `safe=False`. Currently, when one of N ML scanners errors and the rest return clean, `_compute_safe` passes content through in degraded mode. This closes the third link in the RT-075 bypass chain.

## Scope

### Files changed

| File | Change |
|------|--------|
| `petasos/pipeline.py` | Add `partial_failure` to the degraded-mode condition in `_compute_safe` |
| `petasos/config.py` | Add inline comment on `fail_mode` field clarifying tri-state semantics |
| `CLAUDE.md` | Update "Key Design Invariants" to reflect new degraded-mode behavior |
| `tests/adversarial/pipeline/test_degraded_fail_open.py` | Replace bug-confirming test with fix-confirming test; add new mock + 5 new coverage tests |
| `tests/adversarial/pipeline/test_rt075_chain.py` | Remove `xfail` marker from `test_rt075_chain_pipe02_breaks_link3` |

### Files unchanged

- `petasos/premium/` — no premium module changes required.
- `petasos/scanners/` — scanner protocol unchanged.

## Design

### Decision D1: `degraded` aligns with `closed` on partial failure

The brief prescribes this. The `degraded` branch at L116-118 of `pipeline.py` currently checks only `all_ml_failure`. Adding `partial_failure` to the condition makes `degraded` match `closed`'s treatment of scanner health. The remaining distinction between modes:

- **`open`**: ML failures ignored entirely — pass-through.
- **`degraded`**: partial or total ML failure → `safe=False`. Syntactic pre-filter always runs. No early-exit on CRITICAL.
- **`closed`**: same as degraded re ML failure, plus early-exit on CRITICAL from syntactic pre-filter (skips ML fan-out).

### Decision D2: `open` mode unchanged

Operators who choose `open` explicitly accept ML failure risk. This is intentional for debug/low-risk deployments.

### Decision D3: No new fail-mode

A fourth mode was considered and rejected per the brief — the tri-state is sufficient.

### Decision D4: Zero-ML-scanner case unchanged

When `ml_total == 0` (no ML scanners configured), `_compute_safe` returns `safe` based on findings alone. No ML scanners means no ML failure is possible.

### Implementation

**1. `petasos/pipeline.py` — one condition change in `_compute_safe` (L117):**

```python
# Before (L116-118):
if fail_mode == "degraded":
    if all_ml_failure:
        safe = False

# After:
if fail_mode == "degraded":
    if partial_failure or all_ml_failure:
        safe = False
```

**2. `petasos/config.py` — `fail_mode` field comment (L53):**

Add a comment above the `fail_mode` field describing the three modes. This matches the existing style of section comments already in the file (`# Normalization toggles`, `# Scanning`, `# Anonymization`, etc.):

```python
# Scanning
direction: Direction = "inbound"
# open: ML failures ignored (pass-through)
# degraded: partial or total ML failure → safe=False
# closed: same as degraded + early-exit on CRITICAL from syntactic pre-filter
fail_mode: Literal["open", "closed", "degraded"] = "degraded"
```

**3. `CLAUDE.md` — Key Design Invariants update:**

Change the fail-mode bullet from:
> Fail-mode defaults to `degraded` — partial scanner failure passes content; all ML scanners down blocks content

To:
> Fail-mode defaults to `degraded` — partial or total ML scanner failure blocks content; syntactic pre-filter (zero deps) always runs. Configurable to `open` or `closed`.

### RT-075 chain test updates

`test_rt075_chain_pipe02_breaks_link3` in `test_rt075_chain.py` is currently `xfail(reason="Requires PET-49 (PIPE-02) fix in pipeline.py")`. After the fix, this test will pass — the `xfail` marker must be removed so it runs as a normal passing test.

`test_rt075_chain_pre_fix_baseline` has `xfail(strict=False)` and documents the pre-fix state. After PET-49, its first assertion (`safe is True`) will fail because partial ML failure now blocks. The test correctly transitions from XPASS to XFAIL — its semantic role shifts from "confirms the bypass chain is live" to "confirms link 3 is now broken." No change needed.

`test_rt075_chain_all_fixed` requires PET-43 + PET-71 + PET-49. After PET-49 alone, the test stays xfail because NORM-01 and SYN-08 are unfixed — no change needed.

## Test plan

### New mock scanner

Add `_HighFindingScanner` to `tests/adversarial/pipeline/test_degraded_fail_open.py`:

```python
class _HighFindingScanner:
    name = "mock_ml_high"

    async def scan(self, text: str, **kwargs: object) -> ScanResult:
        return ScanResult(
            scanner_name=self.name,
            findings=(
                ScanFinding(
                    rule_id="mock.high",
                    finding_type="test",
                    severity=Severity.HIGH,
                    confidence=1.0,
                    message="mock high finding",
                    scanner_name=self.name,
                ),
            ),
        )
```

### Existing test update

**`test_degraded_partial_ml_failure_still_safe`** → rename to **`test_degraded_partial_ml_failure_blocks`**. Change assertion from `result.safe is True` to `result.safe is False`. Update docstring to reflect the fix.

### New tests (all in `tests/adversarial/pipeline/test_degraded_fail_open.py`)

| # | Test name | Setup | Assert |
|---|-----------|-------|--------|
| 1 | `test_degraded_all_ml_failure_blocks` | 2x `_ErrorScanner`, degraded mode, benign input | `safe is False` |
| 2 | `test_degraded_no_ml_failure_passes` | 2x `_CleanScanner`, degraded mode, benign input | `safe is True` |
| 3 | `test_degraded_partial_ml_failure_with_findings_blocks` | 1x `_ErrorScanner` + 1x `_HighFindingScanner`, degraded mode | `safe is False` |
| 4 | `test_open_partial_ml_failure_passes` | `_ErrorScanner` + `_CleanScanner`, open mode, benign input | `safe is True` |
| 5 | `test_closed_partial_ml_failure_blocks` | `_ErrorScanner` + `_CleanScanner`, closed mode, benign input | `safe is False` |

### RT-075 marker update

Remove `@pytest.mark.xfail(reason="Requires PET-49 (PIPE-02) fix in pipeline.py")` from `test_rt075_chain_pipe02_breaks_link3`.

## Test command

```
python -m pytest tests/adversarial/pipeline/test_degraded_fail_open.py tests/adversarial/pipeline/test_rt075_chain.py -v && ruff check . && ruff format --check . && python -m mypy --strict .
```

## Done when

- [ ] `_compute_safe` treats `partial_failure` as `safe=False` in `degraded` mode (one-line change at L117)
- [ ] `fail_mode` field comment added in `config.py` describing the three modes
- [ ] CLAUDE.md "Key Design Invariants" fail-mode bullet updated to reflect partial failure blocks content
- [ ] Existing test `test_degraded_partial_ml_failure_still_safe` renamed and assertion flipped
- [ ] 6 adversarial tests pass (1 renamed + 5 new) covering all three fail modes with partial/total/no ML failure
- [ ] `test_rt075_chain_pipe02_breaks_link3` xfail marker removed, test passes as normal
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Deferred (P2+)

- **Test #3 combined-scenario overlap**: `test_degraded_partial_ml_failure_with_findings_blocks` uses a HIGH-finding scanner, which makes `safe=False` from findings alone before the fail-mode branch. The test is valid as a combined-scenario exercise but does not uniquely regress the `partial_failure` condition. The renamed test (`test_degraded_partial_ml_failure_blocks`) is the primary regression test for the fix.

## Out of scope

- Scanner health monitoring / circuit breaker (separate feature; would require scanner heartbeat)
- Automatic mode escalation (e.g., auto-switch from `open` to `degraded` on repeated ML failures)
- Per-scanner fail-mode (e.g., one scanner can fail-open while another is fail-closed)
- Drawbridge backport (uncoupled; own ticket if needed)
