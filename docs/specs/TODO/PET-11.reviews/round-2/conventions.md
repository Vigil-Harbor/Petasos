# Conventions Review -- round 2

## Closure of round 1 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 (P2) | MockMLScanner duplicating existing MockScanner | CLOSED | spec v2 line 206: duplication acknowledged as intentional for self-contained E2E |
| F-2 (P2) | MockMLScanner.scan() signature violates Scanner protocol | CLOSED | spec v2 lines 190-201: full type annotations matching protocol |
| F-3 (P2) | asyncio.run() conflicts with asyncio_mode = "auto" | CLOSED | spec v2 Decision 2, Decision 9: switched to new_event_loop pattern |
| F-4 (P2) | v1.0.0 tagging removed without Decision | CLOSED | spec v2 Decision 8 (lines 76-78) and done-when item 10 |
| F-5 (P3) | license module added to coverage -- silent addition | CLOSED | spec v2 Decision 7 (lines 72-74): rationale provided |
| F-6 (P3) | Platform footgun 4c scope reduction | CLOSED | spec v2 Decision 6 (lines 66-71): detailed N/A rationale |
| F-7 (P3) | Test file count 20 should be 18 | CLOSED | spec v2 line 54: corrected |
| F-8 (P2) | PipelineResult.status == "degraded" correctly avoided | CLOSED | spec v2 line 167: references `safe == False` |
| F-9 (P2) | valid_key fixture not in benchmark signature | CLOSED | spec v2 line 243 |

## Findings

### F-1: _alert_manager access claim cites wrong test file as precedent
**Severity:** P4
**Where:** spec line 171
**Evidence:** Spec states "consistent with existing test patterns in `test_premium_integration.py`." That file accesses `pipe._frequency_tracker`, `pipe._license_state`, `pipe._default_profile` -- but never `pipe._alert_manager`. The directional claim (private attribute access is established) is correct, but the specific parenthetical is inaccurate.
**Suggested fix:** Change to "consistent with existing test patterns in `test_premium_integration.py` which access `_frequency_tracker`, `_license_state`, etc."

### F-2: CLAUDE.md coverage targets list omits escalation; spec silently extends it
**Severity:** P3
**Where:** spec line 346 vs CLAUDE.md line 110
**Evidence:** CLAUDE.md states coverage targets as "pipeline/frequency/guard/audit/alerting." Spec done-when adds `escalation` without acknowledgment. Decision 7 covers `license` addition but not `escalation`. Brief also omits `escalation`.
**Suggested fix:** Add `escalation` to Decision 7's rationale alongside `license`.

### F-3: Spec code blocks omit `from __future__ import annotations`
**Severity:** P4
**Where:** spec lines 119-134, 175-202
**Evidence:** All 19 Python files in `tests/` use `from __future__ import annotations` as line 1. Code blocks are illustrative snippets, not complete files.
**Suggested fix:** Add a note that new test files must include the import per repo convention.

### F-4: pytest-benchmark not checked for mypy type stubs
**Severity:** P3
**Where:** spec line 32 vs pyproject.toml mypy overrides
**Evidence:** pyproject.toml has mypy `ignore_missing_imports` overrides for all third-party deps. Spec does not mention whether pytest-benchmark needs one.
**Suggested fix:** Verify stubs and either add override or note it's unnecessary.

### F-5: Decision 1 corrects brief but does not propose updating it
**Severity:** P3
**Where:** spec lines 42-44
**Evidence:** Decision 1 corrects the brief's false claim about license.py. Does not propose amending the brief. Noted for human drift-check.

### F-6: suppressed_count/rate_limited_count are public properties, not private attributes
**Severity:** P4
**Where:** spec line 171
**Evidence:** The properties are `@property` public accessors on `AlertManager`. The private access is `pipe._alert_manager` (Pipeline's internal reference), not the counter properties themselves. Parenthetical "accessing private attributes" is slightly misleading.
**Suggested fix:** Reword to "accessing `pipe._alert_manager` (private Pipeline attribute) to read the public `rate_limited_count`/`suppressed_count` properties."

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 4 | P4: 3

STATUS: GREEN
