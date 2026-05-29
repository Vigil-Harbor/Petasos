# Correctness Review -- round 3

## Closure of round 2 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 (P2) | Frequency weight arithmetic inaccurate | CLOSED | spec v3 line 139: corrected to "triggers 1 injection rule at weight 20.0, plus mock.ml at weight 10.0, totaling 30.0" |
| F-2 (P4) | Anonymization label format wrong | CLOSED | spec v3 line 154: corrected to `<PERSON_1>` |
| F-3 (P3) | Plane ticket not cached in MCP memory | OPEN | Informational -- MCP returns 0 results |

## Findings

### F-1: pytest-benchmark version constraint excludes current stable release and risks incompatibility with project's pytest version
**Severity:** P1
**Where:** spec line 32
**Claim:** "Add `"pytest-benchmark>=4.0,<5"` to `[project.optional-dependencies] dev`"
**Why this is wrong:** The project uses `pytest>=8.0` (pyproject.toml) and currently runs pytest 9.x. `pytest-benchmark` 5.0.0 (released 2024-10-29) introduced fixes specifically for pytest 8.1+ compatibility. The `<5` cap forces installation of pytest-benchmark 4.x, which may produce import errors or hook registration failures with pytest 8.1+/9.x. Current stable: 5.2.3 (2025-11-09).
**Suggested fix:** Change to `"pytest-benchmark>=5.0,<6"`.

### F-2: Plane ticket not cached in MCP memory
**Severity:** P3
Informational -- does not block review.

## Summary
P0: 0 | P1: 1 | P2: 0 | P3: 1 | P4: 0

STATUS: RED P0=0 P1=1 P2=0 P3=1 P4=0
