# PET-51 Spec: Severity-First Finding Merge

**Ticket:** PET-51 (PIPE-04) · **Priority:** High · **OWASP:** ASI07  
**Parent:** PET-14 · **Blocks:** PET-12 (release)

---

## Goal

Fix `merge_findings` in `petasos/pipeline.py` to resolve overlapping positioned findings by severity rank first (CRITICAL > HIGH > MEDIUM > LOW > INFO) and confidence second. The current implementation inverts this, allowing a high-confidence INFO finding to drop an overlapping CRITICAL finding — resulting in `safe=True` when a critical threat was detected.

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/pipeline.py` | Rewrite overlap-resolution logic in `merge_findings` (lines 68–84) |
| `tests/adversarial/pipeline/test_degraded_fail_open.py` | Rename + invert existing test; add 6 new merge tests |

### Files to leave alone

- `petasos/_types.py` — `ScanFinding`, `Position`, `Severity`, `ScanResult` are unchanged
- `petasos/premium/` — no premium code touches merge logic
- `petasos/normalize.py` — normalization is upstream of merge
- `petasos/scanners/` — scanner backends are unchanged
- `tests/test_finding_merge.py` — existing overlap tests use the `_finding()` helper which defaults to `Severity.MEDIUM` for all fixtures; same-severity makes the confidence-vs-severity priority order irrelevant, so behavior is unchanged

## Decisions

### Severity-first, confidence-second

This matches Drawbridge's approach (`clawmoat-drawbridge-sanitizer/src/scanner/index.ts:194–214`) and OWASP ASI07 guidance. A CRITICAL finding with low confidence is more important than an INFO finding with high confidence — the cost of a false negative at CRITICAL far exceeds the cost of a false positive at INFO.

### Equal severity, equal confidence keeps both

When two overlapping findings have identical severity rank and identical confidence, both survive into the merged output. This avoids silent drops and lets downstream consumers (audit, alerting) see the full picture.

### No minimum confidence filter in merge

Confidence floor filtering is a separate stage (Stage 5b in `_inspect_inner`, profile-driven). Merge preserves all findings; filtering is the profile's job. These are orthogonal concerns.

### `_SEVERITY_RANK` remains the canonical ordering

The existing rank map at `pipeline.py:33–39` is correct: `CRITICAL=0, HIGH=1, MEDIUM=2, LOW=3, INFO=4`. Lower rank = higher severity. No changes needed.

## Design

### Current overlap resolution (buggy)

```
if overlap:
    if nxt.confidence > current.confidence:
        current = nxt                    # confidence wins — BUG
    elif nxt.confidence == current.confidence:
        compare severity as tiebreaker
```

### New overlap resolution

```
if overlap:
    nxt_rank = _SEVERITY_RANK.get(nxt.severity, 999)
    cur_rank = _SEVERITY_RANK.get(current.severity, 999)
    if nxt_rank < cur_rank:
        current = nxt                    # higher severity wins
    elif nxt_rank == cur_rank:
        if nxt.confidence > current.confidence:
            current = nxt                # same severity: higher confidence wins
        elif nxt.confidence == current.confidence:
            surviving.append(current)    # identical: keep both
            current = nxt
```

The `.get(severity, 999)` fallback is preserved for defensive coding against unknown severity values, though the `Severity` enum makes this unreachable in practice.

### Concrete code change

In `petasos/pipeline.py`, replace lines 68–84 of `merge_findings`:

**Before:**
```python
for nxt in positioned[1:]:
    assert current.position is not None
    assert nxt.position is not None
    if nxt.position.start < current.position.end:
        if nxt.confidence > current.confidence:
            current = nxt
        elif nxt.confidence == current.confidence:
            nxt_rank = _SEVERITY_RANK.get(nxt.severity, 999)
            cur_rank = _SEVERITY_RANK.get(current.severity, 999)
            if nxt_rank < cur_rank:
                current = nxt
            elif nxt_rank == cur_rank:
                surviving.append(current)
                current = nxt
    else:
        surviving.append(current)
        current = nxt
```

**After:**
```python
for nxt in positioned[1:]:
    assert current.position is not None
    assert nxt.position is not None
    if nxt.position.start < current.position.end:
        nxt_rank = _SEVERITY_RANK.get(nxt.severity, 999)
        cur_rank = _SEVERITY_RANK.get(current.severity, 999)
        if nxt_rank < cur_rank:
            current = nxt
        elif nxt_rank == cur_rank:
            if nxt.confidence > current.confidence:
                current = nxt
            elif nxt.confidence == current.confidence:
                surviving.append(current)
                current = nxt
    else:
        surviving.append(current)
        current = nxt
```

### Invariants preserved

- **Pipeline never throws** — `merge_findings` is a pure function; no exception paths change.
- **Unpositioned findings pass through** — the `unpositioned` list is appended unconditionally (line 87); this logic is untouched.
- **Sort order** — positioned findings are sorted by `position.start` before merge (line 63); unchanged.

## Test plan

### Existing test to update

`test_merge_drops_lower_confidence_critical` in `tests/adversarial/pipeline/test_degraded_fail_open.py` currently asserts the bug: `low_crit not in merged` and `high_info in merged`. Rename to `test_merge_critical_survives_over_high_conf_info` and invert assertions: `low_crit in merged` and `high_info not in merged`.

### New tests (same file)

| Test | Asserts |
|------|---------|
| `test_merge_same_severity_higher_conf_wins` | Overlapping `HIGH/0.5` vs `HIGH/0.9` at overlapping positions — `HIGH/0.9` survives, `HIGH/0.5` dropped |
| `test_merge_same_severity_same_conf_keeps_both` | Overlapping `HIGH/0.8` vs `HIGH/0.8` — both survive in merged output |
| `test_merge_non_overlapping_preserved` | Non-overlapping findings of differing severity — all survive regardless of severity or confidence |
| `test_merge_high_beats_medium_regardless_of_conf` | Overlapping `HIGH/0.3` vs `MEDIUM/0.99` — HIGH survives, MEDIUM absent, `len(merged) == 1` |
| `test_merge_unpositioned_always_kept` | Unpositioned findings are never dropped by overlap logic |
| `test_merge_critical_as_nxt_beats_earlier_info` | INFO at [0,10) then CRITICAL at [5,15) — CRITICAL arrives as `nxt`, wins via `nxt_rank < cur_rank`, INFO dropped |
| `test_pipeline_critical_low_conf_still_blocks` | Full pipeline end-to-end: CRITICAL finding at any confidence produces `safe=False` |

### Regression guard

The renamed test `test_merge_critical_survives_over_high_conf_info` is the direct regression guard — it asserts the exact scenario from the bug report.

## Test command

```bash
C:/Users/zioni/Documents/Vigil-Harbor/Petasos/.venv/Scripts/python.exe -m pytest tests/adversarial/pipeline/test_degraded_fail_open.py -v
```

## Done when

- [ ] `merge_findings` compares severity rank first, confidence second
- [ ] Existing `test_merge_drops_lower_confidence_critical` updated to assert CRITICAL survives
- [ ] All 8 tests listed above pass
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite
- [ ] After merge, run `/wiki-after-merge` and update all wiki references to merge priority (architecture.md line 36 and comprehension/2026-05-25-pet-6-pipeline-orchestrator.md line 18) from "highest confidence wins" / "prefer higher confidence" to "highest severity wins"

## Out of scope

- Multi-position overlap (finding spans multiple disjoint ranges) — not supported by current `Position` dataclass
- Transitive overlap window contraction — when a dropped finding's span extends beyond the winner's position, the effective overlap window shrinks. Subsequent findings that would have overlapped the dropped finding may survive as false non-overlaps. This is a pre-existing limitation of the greedy merge algorithm (present in the current confidence-first code too), not introduced or worsened by this fix. Fixing it requires tracking a running overlap-end separate from `current.position.end`, which changes the merge algorithm's semantics
- NaN confidence handling — if a scanner returns `confidence=float('nan')`, IEEE 754 causes all comparisons to return False, silently dropping findings. This is a pre-existing issue (the current confidence-first code has the same bug). Confidence validation is the scanner's responsibility; adding a NaN guard in merge is a separate concern from the severity/confidence priority inversion
- Weighted merge across scanner trust levels (e.g., ML scanner findings weighted higher than syntactic) — future work
- Confidence calibration across scanners (different scanners may have different confidence scales) — separate concern
- Drawbridge backport (already uses severity-first; no change needed)
- `_SEVERITY_RANK` deduplication — the rank map is duplicated in `pipeline.py` and `alerting.py`. Consolidating to a shared constant in `_types.py` is desirable but orthogonal to the merge fix
