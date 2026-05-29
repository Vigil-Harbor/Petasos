# PET-65 Edge-Cases Review -- Round 1

## Findings

### F-1: ModuleNotFoundError vs ImportError not documented (P3)
Python 3.11+ raises ModuleNotFoundError (subclass) for missing packages. except ImportError catches both. Works correctly but intent undocumented.

### F-2: _is_missing_package does not test empty-string name (P3)
ImportError(name="") returns False by coincidence (not in expected set). Test plan misses this.

### F-3: __all__ duplicates on importlib.reload() (P4)
Not an issue -- __all__ is re-initialized from scratch. Safe.

### F-4: Integration tests need sys.modules manipulation guidance (P2)
Tests 5-7 require re-importing module-level code. Spec doesn't describe the sys.modules cleanup mechanism. Risk of flaky tests.

### F-5: Log %s formatting is safe (P4)
Correct pattern, no injection risk. No finding.

### F-6: Circular import risk from logging import (P4)
No risk -- stdlib module. No finding.

### F-7: del _exc retained but rationale not explained (P4)
Breaks traceback reference at module scope, preventing memory leak. Should have a note.

### F-8: No integration test for Presidio __all__ += pattern (P2)
Presidio uses __all__ += [...] (two symbols) vs .append() for others. No test covers this distinct path.

### F-9: Empty expected_names set silently returns False (P3)
Safe direction (re-raises), but a caller bug would go undetected.

### F-10: Bare ImportError re-raise lacks integration test (P2)
Done-when criterion requires bare ImportError re-raises in all blocks, but only unit-tested.

### F-11: Line number references are fragile (P4)
May go stale if prior changes shift lines.

### F-12: mypy strict compatibility with set[str] (P4)
No issue with from __future__ import annotations.

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 3 | P4: 5

STATUS: GREEN
