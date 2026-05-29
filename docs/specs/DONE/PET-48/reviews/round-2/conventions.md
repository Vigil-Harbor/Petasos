# Conventions Review -- round 2

## Closure of round 1 findings

All round 1 findings CLOSED. D6 citations corrected, import placement specified, pytest --cov restored.

## Findings

### F-1: `_logger` placement after TYPE_CHECKING block breaks convention
**Severity:** P2
All 4 Petasos modules with logging place `_logger` BEFORE the `if TYPE_CHECKING:` block. Spec places it after.

### F-2: D7 (KI/SE catch) is spec-level addition with rationale
**Severity:** P3
Category (c) — brief authorizes `except BaseException` but doesn't explicitly discuss the trade-off. Surfacing for drift-check.

### F-3: Error format change in `_scan_one` is spec-level addition
**Severity:** P3
Brief doesn't mention changing error format from `str(exc)` to type-name format. Well-motivated but caller-visible change.

### F-4: Test command uses C:/python310/python.exe
**Severity:** P4
Accepted convention per prior reviews.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 2 | P4: 1

STATUS: GREEN
