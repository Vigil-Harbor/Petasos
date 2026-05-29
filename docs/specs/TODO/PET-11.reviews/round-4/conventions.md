# Conventions Review -- round 4

## Closure of round 3 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 (P4) | Code blocks omit `from __future__ import annotations` | OPEN | P4 -- illustrative snippets |
| F-2 (P3) | pyproject.toml modification incomplete -- missing mypy override | CLOSED | spec v4: mypy override for `pytest_benchmark` added to Files to modify |
| F-3 (P3) | Decision 1 corrects brief without proposing update | OPEN | P3 -- informational for drift-check |
| F-4 (P3) | Done-when item 4 (callback confirmation) is spec-level addition | OPEN | P3 -- valid decomposition |
| F-5 (P4) | Security hardening checklist creation is authorized by brief | OPEN | P4 -- confirmed authorized |

## Findings

### F-1: Code blocks omit `from __future__ import annotations` (carried)
**Severity:** P4
**Where:** spec code blocks throughout
**Suggested fix:** Note that new test files must include the import per repo convention.

### F-2: Decision 1 corrects brief without proposing update (carried)
**Severity:** P3
**Where:** spec lines 42-44
**Suggested fix:** Note brief should be annotated. Informational for drift-check.

### F-3: Decision 9 partially duplicates Decision 2
**Severity:** P4
**Where:** spec Decisions section
Decision 9 (new_event_loop pattern for benchmarks) overlaps with Decision 2 (new_event_loop pattern for async tests). The scope differs (benchmarks vs tests) but the rationale is identical.
Informational -- not a defect.

### F-4: Done-when item 4 (callback confirmation) is spec-level addition (carried)
**Severity:** P3
Informational -- valid decomposition of brief scope into verifiable criterion.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 3 | P4: 1 (F-3 new)

STATUS: GREEN
