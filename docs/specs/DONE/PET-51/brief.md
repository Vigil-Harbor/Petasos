# PET-51 — PIPE-04: Finding Merge Drops CRITICAL in Favor of Higher-Confidence INFO

**Plane:** PET-51 · **Finding:** PIPE-04 · **Priority:** High  
**OWASP:** ASI07 — Insufficient threat-detection coverage  
**Parent:** PET-14 · **Blocks:** PET-12 (release)  
**Status:** Backlog → ready-for-dev

---

## Problem

`merge_findings` at `petasos/pipeline.py:44–87` deduplicates overlapping positioned findings. When two findings overlap (L71: `nxt.position.start < current.position.end`), the merge resolves by confidence first (L72: `if nxt.confidence > current.confidence`), and only falls through to severity comparison at equal confidence (L74–78).

Attack scenario: Scanner A reports `CRITICAL / confidence=0.5` at position `[0,10)`. Scanner B reports `INFO / confidence=0.99` at position `[5,15)`. These overlap. Because `0.99 > 0.5`, the CRITICAL finding is dropped and only the INFO finding survives. Downstream, `_compute_safe` (L96–99) checks for `CRITICAL` or `HIGH` severity — the dropped CRITICAL means `safe=True`.

The existing test `test_merge_drops_lower_confidence_critical` (`tests/adversarial/pipeline/test_degraded_fail_open.py:41–68`) explicitly asserts this behavior — `low_crit not in merged` and `high_info in merged` — confirming the bug.

## Prior Art

Drawbridge's TypeScript scanner (`clawmoat-drawbridge-sanitizer/src/scanner/index.ts:194–214`) merges by severity first: the comment at L194 reads "highest severity wins" and the merge uses `effectiveSeverityRank` to compare, not confidence. Confidence is not consulted during Drawbridge dedup. Petasos inverted this priority, creating a regression from the Drawbridge design.

OWASP ASI07 guidance: when multiple detectors produce overlapping signals, the highest-severity signal must survive aggregation. A confidence score reflects detector certainty; severity reflects impact. Impact must dominate certainty in security contexts.

## Remediation

### Approach: Merge by severity rank first, confidence as tiebreaker

Invert the comparison order: severity rank (lower rank = higher severity) is the primary key; confidence is the secondary key within equal severity.

### Changes

**1. `petasos/pipeline.py` — `merge_findings` L68–81**

Current:

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

Replace with:

```python
for nxt in positioned[1:]:
    assert current.position is not None
    assert nxt.position is not None
    if nxt.position.start < current.position.end:
        nxt_rank = _SEVERITY_RANK.get(nxt.severity, 999)
        cur_rank = _SEVERITY_RANK.get(current.severity, 999)
        if nxt_rank < cur_rank:
            # Higher severity wins regardless of confidence
            current = nxt
        elif nxt_rank == cur_rank:
            # Same severity: higher confidence wins
            if nxt.confidence > current.confidence:
                current = nxt
            elif nxt.confidence == current.confidence:
                # Identical severity + confidence: keep both
                surviving.append(current)
                current = nxt
    else:
        surviving.append(current)
        current = nxt
```

This restores the Drawbridge invariant: severity dominates confidence during overlap resolution.

### Tests Required

| Test | File | Asserts |
|------|------|---------|
| `test_merge_critical_survives_over_high_conf_info` | `tests/adversarial/pipeline/test_degraded_fail_open.py` | Overlapping `CRITICAL/0.5` vs `INFO/0.99` → CRITICAL survives |
| `test_merge_same_severity_higher_conf_wins` | `tests/adversarial/pipeline/test_degraded_fail_open.py` | Overlapping `HIGH/0.5` vs `HIGH/0.9` → `HIGH/0.9` survives |
| `test_merge_same_severity_same_conf_keeps_both` | `tests/adversarial/pipeline/test_degraded_fail_open.py` | Overlapping `HIGH/0.8` vs `HIGH/0.8` → both survive |
| `test_merge_non_overlapping_preserved` | `tests/adversarial/pipeline/test_degraded_fail_open.py` | Non-overlapping findings of any severity → all survive |
| `test_merge_high_beats_medium_regardless_of_conf` | `tests/adversarial/pipeline/test_degraded_fail_open.py` | Overlapping `HIGH/0.3` vs `MEDIUM/0.99` → HIGH survives |
| `test_merge_unpositioned_always_kept` | `tests/adversarial/pipeline/test_degraded_fail_open.py` | Unpositioned findings pass through regardless of overlap logic |
| `test_pipeline_critical_low_conf_still_blocks` | `tests/adversarial/pipeline/test_degraded_fail_open.py` | Full pipeline: CRITICAL at any confidence → `safe=False` |

### What the existing test needs

`test_merge_drops_lower_confidence_critical` currently asserts `low_crit not in merged`. After the fix, invert the assertions: `low_crit in merged` and `high_info not in merged`. Rename to `test_merge_critical_survives_over_high_conf_info`.

## Decisions Carried Forward

- **Severity-first, confidence-second.** This matches Drawbridge's approach and security best practice. A CRITICAL finding with low confidence is still more important than an INFO finding with high confidence — the cost of a false negative at CRITICAL far exceeds the cost of a false positive at INFO.
- **Equal severity, equal confidence → keep both.** When two findings have identical severity and confidence, both survive. This avoids silent drops and lets downstream consumers (audit, alerting) see the full picture.
- **No minimum confidence filter in merge.** Confidence floor filtering is a separate stage (L381–386, profile-driven). Merge should preserve all findings; filtering is the profile's job.
- **`_SEVERITY_RANK` remains the canonical ordering.** The existing rank map (L33–39) is correct: CRITICAL=0, HIGH=1, MEDIUM=2, LOW=3, INFO=4. Lower rank = higher severity.

## Done When

- [ ] `merge_findings` compares severity rank first, confidence second
- [ ] Existing `test_merge_drops_lower_confidence_critical` updated to assert CRITICAL survives
- [ ] All 7 tests listed above pass
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of Scope

- Multi-position overlap (finding spans multiple disjoint ranges) — not supported by current `Position` dataclass
- Weighted merge across scanner trust levels (e.g., ML scanner findings weighted higher than syntactic) — future work
- Confidence calibration across scanners (different scanners may have different confidence scales) — separate concern
- Drawbridge backport (already uses severity-first; no change needed)
