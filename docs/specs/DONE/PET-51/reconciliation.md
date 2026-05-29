# Reconciliation Report: PET-51

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-51.spec.md
> Merge: PR #22 (69aa2c6)
> Plane state: Done (group: completed)

## Summary
The shipped commit 69aa2c6 implements the severity-first finding merge exactly as the spec and brief prescribe — `merge_findings` now compares `_SEVERITY_RANK` first and confidence second, and all 8 named tests are present and pass. The only open item is the post-merge wiki-text update (architecture.md still reads "highest confidence wins"), which is a spec "Done when" bullet that remains unmet.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/pipeline.py` | Yes | Overlap resolution rewritten at L85–98; matches spec "After" block byte-for-byte. Current on-disk code confirms severity-first, confidence-second. |
| `tests/adversarial/pipeline/test_degraded_fail_open.py` | Yes | Existing test renamed + assertions inverted; 7 new tests added (216 insertions). |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-51.test-output.txt` — pytest run-evidence artifact added by the ship-spec flow (11 passed). Documentation/process artifact, not a code or behavior change; no functional drift.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | Severity-first, confidence-second | Confirmed | pipeline.py:86-95 — `nxt_rank`/`cur_rank` compared first; `nxt.confidence` only consulted inside `elif nxt_rank == cur_rank`. |
| 2 | Equal severity + equal confidence keeps both | Confirmed | pipeline.py:93-95 — on `nxt.confidence == current.confidence`, `surviving.append(current)` then `current = nxt`; test_merge_same_severity_same_conf_keeps_both asserts both survive (test file:175). |
| 3 | No minimum confidence filter in merge | Confirmed | merge_findings (pipeline.py:58-101) contains no confidence-floor filter; only positional overlap + severity/confidence resolution. Unpositioned findings appended unconditionally (L101). |
| 4 | `_SEVERITY_RANK` remains canonical ordering | Confirmed | pipeline.py:38-44 — CRITICAL=0, HIGH=1, MEDIUM=2, LOW=3, INFO=4; unchanged by diff. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `merge_findings` compares severity rank first, confidence second | Met | pipeline.py:85-98 (severity rank branch precedes confidence branch). |
| 2 | Existing `test_merge_drops_lower_confidence_critical` updated to assert CRITICAL survives | Met | Renamed to `test_merge_critical_survives_over_high_conf_info` (test file:115); asserts `low_crit in merged` / `high_info not in merged`. |
| 3 | All 8 tests pass (renamed + 7 new) | Met | All 8 functions present (test file:115,145,175,205,235,266,295,326); PET-51.test-output.txt shows 11 passed in 0.03s. |
| 4 | `ruff check .` and `mypy --strict .` clean | Unverifiable | Not re-run in this read-only pass; test-output.txt captures pytest only, not lint/type results. |
| 5 | No regression in full `pytest` suite | Unverifiable | Not re-run here; shipped evidence covers only the target test file (11 tests). |
| 6 | After merge, update wiki references (architecture.md L36 + comprehension pipeline-orchestrator L18) from "highest confidence wins" to "highest severity wins" | Unmet | architecture.md:36 still reads "Merge findings (dedup overlapping positions, highest confidence wins)". Comprehension file `*pipeline-orchestrator*` not found at the cited path. This is a `/spec-retire`/`/wiki-after-merge` lifecycle step still outstanding; no impact on shipped code correctness. |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| test_merge_critical_survives_over_high_conf_info | Yes | tests/adversarial/pipeline/test_degraded_fail_open.py:115 |
| test_merge_same_severity_higher_conf_wins | Yes | tests/adversarial/pipeline/test_degraded_fail_open.py:145 |
| test_merge_same_severity_same_conf_keeps_both | Yes | tests/adversarial/pipeline/test_degraded_fail_open.py:175 |
| test_merge_non_overlapping_preserved | Yes | tests/adversarial/pipeline/test_degraded_fail_open.py:205 |
| test_merge_high_beats_medium_regardless_of_conf | Yes | tests/adversarial/pipeline/test_degraded_fail_open.py:235 |
| test_merge_unpositioned_always_kept | Yes | tests/adversarial/pipeline/test_degraded_fail_open.py:266 |
| test_merge_critical_as_nxt_beats_earlier_info | Yes | tests/adversarial/pipeline/test_degraded_fail_open.py:295 |
| test_pipeline_critical_low_conf_still_blocks | Yes | tests/adversarial/pipeline/test_degraded_fail_open.py:326 |

## Wiki-ready
- Severity dominates confidence in overlap resolution: a CRITICAL/low-confidence finding must survive over an INFO/high-confidence finding (OWASP ASI07; restores the Drawbridge `scanner/index.ts:194-214` "highest severity wins" invariant). This contradicts the still-stale architecture.md:36 wording ("highest confidence wins") — the wiki text must be corrected as part of retire.

RECONCILED: no DRIFT: 1
