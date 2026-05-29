# Conventions Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: D6 incorrectly cites `audit.py` as having a logger
**Severity:** P2
`petasos/premium/audit.py` has no `import logging` or `_logger`. Correct examples: `alerting.py`, `guard.py`, `profiles/__init__.py`.

### F-2: `import logging` placement instruction ambiguous relative to isort
**Severity:** P3
"After the existing imports" could place it after third-party imports, violating ruff I001.

### F-3: `pytest --cov` moved from Done-when to Out of Scope
**Severity:** P3
Spec provides rationale. Surfacing for visibility.

### F-4: Test command uses `C:/python310/python.exe`
**Severity:** P4
Path name implies 3.10 but project requires 3.11+. Same path used in prior specs; accepted convention.

### F-5: D6 logger addition promoted to named Decision
**Severity:** P4
Reasonable escalation. Brief authorized logging; spec made prerequisite explicit.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 2 | P4: 2

STATUS: GREEN
