# PET-65 — SCAN-07: Import Guard Swallows Non-Missing-Dep ImportErrors

**Plane:** PET-65 · **Finding:** SCAN-07 · **Priority:** High
**Parent:** PET-14 · **Blocks:** PET-12 (release)

---

## Goal

Harden the optional-scanner import guards in `petasos/scanners/__init__.py` so that only genuine "package not installed" `ImportError`s are swallowed, all other `ImportError`s (transitive dependency failures, broken installs, internal submodule errors) propagate, and every swallowed error emits a `DEBUG` log entry for operator diagnostics.

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/scanners/__init__.py` | Extract `_is_missing_package()` helper; replace inline `getattr` checks; add `logging` import and `_logger`; add `_logger.debug()` on each swallow path |

### Files to create

| File | Purpose |
|------|---------|
| `tests/test_scanner_init.py` | 11 tests (4 unit, 7 integration) covering the helper function and the import-guard behavior |

### Files to leave alone

- `petasos/scanners/minimal.py` — MinimalScanner is always present; no guard needed
- `petasos/scanners/llm_guard.py`, `llama_firewall.py`, `presidio.py` — internal `_ensure_loaded()` logic unchanged
- `petasos/pipeline.py` — pipeline consumes scanners from `__all__`; no change needed
- All premium modules — unrelated to import guards

## Decisions

### Decision 1: `debug` level, not `warning`

Missing extras are a normal deployment scenario (`pip install petasos` without extras). Warning-level logging would create noise for the base-install case. Operators who need to diagnose missing scanners set `petasos.scanners` to DEBUG. This matches the brief's explicit decision.

### Decision 2: Helper function, not inline checks

The `_is_missing_package()` helper centralizes the guard logic, makes it independently testable, and documents the security-relevant intent in one place. Three import blocks share identical logic — extracting it eliminates duplication and reduces the chance of a guard diverging in a future edit.

### Decision 3: No submodule matching — exact top-level name only

The helper checks `exc.name in expected_names` for exact top-level package names. A failure in `llm_guard.submodule` will have `name="llm_guard.submodule"`, which does not match `"llm_guard"`, so it correctly re-raises. This is the tightest possible guard without false negatives.

### Decision 4: Bare ImportError always re-raises

`ImportError("message")` without `name=` yields `getattr(exc, "name", None) == None`. The helper returns `False`, so the caller re-raises. This is already the behavior of the current code, but the helper makes the intent explicit and testable.

## Design

### 1. `_is_missing_package()` helper

Add a module-level helper function between the `__all__` declaration and the first `try` block:

```python
import logging

_logger = logging.getLogger(__name__)


def _is_missing_package(exc: ImportError, expected_names: set[str]) -> bool:
    """Return True only if exc is a top-level 'module not found' for one of
    the expected package names."""
    exc_name = getattr(exc, "name", None)
    if exc_name is None:
        return False
    return exc_name in expected_names
```

### 2. Rewrite each import block

Each of the three `try/except` blocks follows the same pattern:

```python
try:
    from petasos.scanners.<module> import <Scanner>
    __all__.append("<Scanner>")
except ImportError as _exc:
    if not _is_missing_package(_exc, {<expected_names>}):
        raise
    _logger.debug("<Scanner> not available: %s", _exc)
    del _exc
```

Concrete changes per block:

- **LlmGuardScanner (L7–14):** Replace `if getattr(_exc, "name", None) != "llm_guard": raise` with `if not _is_missing_package(_exc, {"llm_guard"}): raise`. Add `_logger.debug("LlmGuardScanner not available: %s", _exc)`.
- **LlamaFirewallScanner (L16–23):** Replace `if getattr(_exc, "name", None) not in ("llamafirewall", "llama_firewall"): raise` with `if not _is_missing_package(_exc, {"llamafirewall", "llama_firewall"}): raise`. Add `_logger.debug("LlamaFirewallScanner not available: %s", _exc)`.
- **PresidioScanner (L25–32):** Replace `if getattr(_exc, "name", None) not in ("presidio_analyzer", "presidio_anonymizer"): raise` with `if not _is_missing_package(_exc, {"presidio_analyzer", "presidio_anonymizer"}): raise`. Add `_logger.debug("PresidioScanner not available: %s", _exc)`.

### 3. Final file structure

```python
from __future__ import annotations

import logging

from petasos.scanners.minimal import MinimalScanner

__all__: list[str] = ["MinimalScanner"]

_logger = logging.getLogger(__name__)


def _is_missing_package(exc: ImportError, expected_names: set[str]) -> bool:
    """Return True only if exc is a top-level 'module not found' for one of
    the expected package names."""
    exc_name = getattr(exc, "name", None)
    if exc_name is None:
        return False
    return exc_name in expected_names


try:
    from petasos.scanners.llm_guard import LlmGuardScanner  # noqa: F401
    __all__.append("LlmGuardScanner")
except ImportError as _exc:
    if not _is_missing_package(_exc, {"llm_guard"}):
        raise
    _logger.debug("LlmGuardScanner not available: %s", _exc)
    del _exc

try:
    from petasos.scanners.llama_firewall import LlamaFirewallScanner  # noqa: F401
    __all__.append("LlamaFirewallScanner")
except ImportError as _exc:
    if not _is_missing_package(_exc, {"llamafirewall", "llama_firewall"}):
        raise
    _logger.debug("LlamaFirewallScanner not available: %s", _exc)
    del _exc

try:
    from petasos.scanners.presidio import PresidioScanner, anonymize
    __all__ += ["PresidioScanner", "anonymize"]
except ImportError as _exc:
    if not _is_missing_package(_exc, {"presidio_analyzer", "presidio_anonymizer"}):
        raise
    _logger.debug("PresidioScanner not available: %s", _exc)
    del _exc
```

## Test plan

All tests in `tests/test_scanner_init.py`. Tests exercise the `_is_missing_package()` helper directly and the import-guard integration behavior via module-level patching.

### Unit tests for `_is_missing_package()`

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_is_missing_package_matches_expected_name` | `_is_missing_package(ImportError(name="llm_guard"), {"llm_guard"})` returns `True` |
| 2 | `test_is_missing_package_rejects_unexpected_name` | `_is_missing_package(ImportError(name="torch"), {"llm_guard"})` returns `False` |
| 3 | `test_is_missing_package_rejects_none_name` | `_is_missing_package(ImportError("broken"), {"llm_guard"})` returns `False` |
| 4 | `test_is_missing_package_rejects_submodule` | `_is_missing_package(ImportError(name="llm_guard.submodule"), {"llm_guard"})` returns `False` |

### Integration tests for import-guard behavior

Integration tests must remove `petasos.scanners` (and its submodule entries) from `sys.modules` before re-import, and restore original state in teardown, to avoid cross-test pollution. Use a pytest fixture that snapshots and restores `sys.modules`.

Note: the brief's `test_transitive_dep_failure_reraises` is subsumed by `test_broken_extra_reraises`; replaced with `test_is_missing_package_rejects_submodule` (unit test #4) to cover the submodule re-raise path per Decision 3.

| # | Test | Asserts |
|---|------|---------|
| 5 | `test_broken_extra_reraises` | Patching `petasos.scanners.llm_guard` to raise `ImportError(name="torch")` — re-importing `petasos.scanners` raises `ImportError` |
| 6 | `test_bare_importerror_reraises` | Patching `petasos.scanners.llm_guard` to raise `ImportError("broken dependency")` (no `name=`) — re-importing `petasos.scanners` raises `ImportError` |
| 7 | `test_missing_extra_removes_from_all` | Patching `petasos.scanners.llm_guard` to raise `ImportError(name="llm_guard")` — `LlmGuardScanner` absent from `__all__` |
| 8 | `test_missing_extra_logs_debug` | Same patch as #7 — capturing log output at DEBUG confirms `"LlmGuardScanner not available"` message |
| 9 | `test_missing_presidio_removes_both_from_all` | Patching `petasos.scanners.presidio` to raise `ImportError(name="presidio_analyzer")` — neither `"PresidioScanner"` nor `"anonymize"` appear in `__all__` |
| 10 | `test_missing_llama_removes_from_all` | Patching `petasos.scanners.llama_firewall` to raise `ImportError(name="llamafirewall")` — `LlamaFirewallScanner` absent from `__all__` |
| 11 | `test_minimal_always_present` | `MinimalScanner` is always in `petasos.scanners.__all__` regardless of extras availability |

### Existing test update

None. Existing scanner tests (`test_llm_guard_scanner.py`, etc.) test scanner behavior, not import guards. No existing test references `_is_missing_package` or the `__init__.py` guard logic.

## Test command

```
py -3.13 -m pytest tests/test_scanner_init.py -v && py -3.13 -m pytest --tb=short -q && ruff check . && ruff format --check . && mypy --strict .
```

## Done when

- [ ] `_is_missing_package()` helper extracted and used in all three import blocks
- [ ] `_logger.debug()` emitted on every swallowed ImportError
- [ ] Bare `ImportError("message")` (no `name`) re-raises in all three blocks
- [ ] `ImportError(name="unexpected_module")` re-raises in all three blocks
- [ ] Submodule `ImportError(name="llm_guard.submodule")` re-raises (not swallowed)
- [ ] All 11 tests pass
- [ ] `ruff check .`, `ruff format --check .`, and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Deferred (P2+)

- **Brief test count stale (P2):** Brief Done When says "8 tests"; spec has 11. Spec's Done When is authoritative. The brief is not updated because it is background material.
- **Done-when "all three blocks" vs single-block integration tests (P3):** Done-when criteria #3/#4 say "all three blocks" but integration tests only cover llm_guard. Shared helper provides logical coverage; implementer may add parametrized variants if desired.
- **Alternate expected_names not integration-tested (P3):** `llama_firewall` and `presidio_anonymizer` names only covered by unit-level set membership. Safe — set lookup is deterministic.

## Out of scope

- Runtime scanner health monitoring / heartbeat (tracked separately in pipeline orchestration)
- Auto-installation of missing extras (not appropriate for a security library)
- `__init__.py` as a scanner registry with dynamic discovery (current static imports are sufficient)
- Drawbridge backport (Drawbridge uses a different pattern; its own ticket if needed)
- Changes to scanner modules themselves — fix is entirely in `__init__.py`
