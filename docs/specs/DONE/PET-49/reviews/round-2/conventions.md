# Conventions Review -- round 2

## Closure of round 1 findings

All round 1 P1 findings CLOSED:
- F-3 (P1): config.py comment reinstated

All P2 findings CLOSED:
- F-1: CLAUDE.md in scope
- F-2: fabricated convention removed

## Findings

### F-1: Test command uses `python -m pytest/mypy` instead of bare commands
**Severity:** P4

### F-2: config.py multi-line per-value comment is a new style
**Severity:** P4 (acceptable — brief explicitly requires it)

### F-3: Wiki architecture.md fail-mode description will become stale
**Severity:** P3 (handled by post-merge wiki-after-merge workflow)

### F-4: CLAUDE.md "Before" quote truncated
**Severity:** P4

### F-5: Done-When missing CLAUDE.md update item
**Severity:** P2
Files Changed table lists CLAUDE.md but Done-When has no corresponding item.
**Suggested fix:** Add Done-When item for CLAUDE.md update.

### F-6: Brief "docstring" vs spec "comment" wording
**Severity:** P3 ("comment" is more accurate for frozen dataclass)

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 2 | P4: 3

STATUS: GREEN
