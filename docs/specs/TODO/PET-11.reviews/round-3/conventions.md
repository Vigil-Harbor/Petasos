# Conventions Review -- round 3

## Closure of round 2 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 (P4) | _alert_manager precedent cites wrong file | CLOSED | spec v3 line 171: reworded accurately |
| F-2 (P3) | CLAUDE.md coverage targets omit escalation | CLOSED | spec v3 Decision 7: rationale covers both escalation and license |
| F-3 (P4) | Code blocks omit `from __future__ import annotations` | OPEN | P4 -- illustrative snippets |
| F-4 (P3) | pytest-benchmark mypy stubs unaddressed | OPEN | P3 -- no mypy override mentioned |
| F-5 (P3) | Decision 1 corrects brief without proposing update | OPEN | P3 -- informational for drift-check |
| F-6 (P4) | suppressed_count is public property | CLOSED | spec v3 line 171: correctly described |

## Findings

### F-1: Code blocks omit `from __future__ import annotations` (carried from round 2)
**Severity:** P4
**Where:** spec code blocks throughout
**Suggested fix:** Add note that new test files must include the import per repo convention.

### F-2: pyproject.toml modification incomplete -- missing mypy override for pytest-benchmark (carried from round 2)
**Severity:** P3
**Where:** spec line 32
**Suggested fix:** Add `"pytest_benchmark"` to mypy overrides or verify stubs.

### F-3: Decision 1 corrects brief without proposing update (carried from round 2)
**Severity:** P3
**Where:** spec lines 42-44
**Suggested fix:** Note brief should be annotated. Informational for drift-check.

### F-4: Done-when item 4 (callback confirmation) is spec-level addition
**Severity:** P3
**Where:** spec line 344
Informational -- valid decomposition of brief scope into verifiable criterion.

### F-5: Security hardening checklist creation is authorized by brief
**Severity:** P4
Informational -- confirmed authorized.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 3 | P4: 2

STATUS: GREEN
