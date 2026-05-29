# PET-65 — SCAN-07: Import Guard Swallows Non-Missing-Dep ImportErrors

**Plane:** PET-65 · **Finding:** SCAN-07 · **Priority:** High  
**OWASP:** ASI07 — Insufficient AI model and component monitoring  
**Parent:** PET-14 · **Blocks:** PET-12 (release)  
**Status:** refuted (code review) → ready-for-dev

---

## Problem

`petasos/scanners/__init__.py` (L7–32) uses `try/except ImportError` blocks to conditionally import optional scanner backends. Each block checks `getattr(_exc, "name", None)` against expected package names to distinguish "extra not installed" from other import failures:

```python
try:
    from petasos.scanners.llm_guard import LlmGuardScanner  # noqa: F401
    __all__.append("LlmGuardScanner")
except ImportError as _exc:
    if getattr(_exc, "name", None) != "llm_guard":
        raise
    del _exc
```

The guard is checking `_exc.name` — the `name` attribute of `ImportError`, which is set when `import X` fails because module `X` is not found. The check correctly re-raises when the `name` attribute doesn't match the expected package name. However, there are failure scenarios where this guard silently drops a scanner the operator expects:

**1. Transitive dependency ImportError with matching name (L11–13, L21–22, L30).**

If `llm_guard` is installed but one of its internal submodules raises an `ImportError` whose `name` attribute happens to match the guard string (e.g., a submodule named `llm_guard` within the package), the error is silently swallowed. The scanner disappears from `__all__` with no log entry.

**2. ImportError with `name=None` (L12, L21, L30).**

When `ImportError` is raised with a bare message (no `name` kwarg) — e.g., `raise ImportError("broken dependency")` — `getattr(_exc, "name", None)` returns `None`. Since `None != "llm_guard"`, this correctly re-raises. This path is safe.

**3. The real gap: no logging on swallow.**

When the guard does swallow (package genuinely not installed), there is zero log output. An operator who installs `petasos[llm-guard]` but has a broken install gets no feedback — the scanner silently vanishes from `__all__` and from the pipeline. The operator expects LlmGuardScanner to be available but gets only MinimalScanner, with no error, no warning, no audit trail.

The LlamaFirewall guard at L17–22 checks against two names (`"llamafirewall"`, `"llama_firewall"`), and Presidio at L26–30 checks against two names (`"presidio_analyzer"`, `"presidio_anonymizer"`). The multi-name check itself is correct, but the silent-swallow problem applies to all three blocks.

## Prior Art

Drawbridge is TypeScript/npm and uses a different mechanism — ClawMoat is an optional peer dependency with a runtime availability check (`try { require('clawmoat') }`) that logs a warning on failure. The Drawbridge pipeline explicitly logs when ClawMoat is unavailable and falls back to syntactic-only mode with a visible status indicator.

Python ecosystem convention for extras-based optional imports typically includes either a `warnings.warn()` call or a `logging.debug()`/`logging.info()` call so that diagnostic output is available.

## Remediation

### Approach: Re-raise non-missing-dep ImportErrors; log on genuine missing-dep swallow

### Changes

**1. `petasos/scanners/__init__.py` — add logging and tighten guards (L1–32)**

Replace the entire file with tightened import guards:

```python
from __future__ import annotations

import logging

from petasos.scanners.minimal import MinimalScanner

__all__: list[str] = ["MinimalScanner"]

_logger = logging.getLogger(__name__)


def _is_missing_package(exc: ImportError, expected_names: set[str]) -> bool:
    """Return True only if the ImportError is a top-level 'module not found'
    for one of the expected package names. Any other ImportError — including
    transitive failures, broken installs, or syntax errors in the extra —
    must propagate."""
    exc_name = getattr(exc, "name", None)
    if exc_name is None:
        return False
    # Only match if the missing module is the top-level package itself,
    # not a submodule (e.g., "llm_guard.broken_sub" should not match "llm_guard")
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

Key changes:
- **Extracted `_is_missing_package()` helper** — centralizes the guard logic, makes it testable, and documents the intent.
- **`exc_name is None` returns `False`** — bare `ImportError("message")` with no `name` attribute always re-raises. This is the correct behavior and was already working, but the helper makes it explicit.
- **`_logger.debug()` on swallow** — operators running with `DEBUG` logging see which scanners were skipped and why. This is the minimum viable observability.

**2. No changes to scanner modules themselves.** The fix is entirely in `__init__.py`. Each scanner module's internal `_ensure_loaded()` already handles its own import errors and returns `ScanResult(error=...)`.

### Tests Required

| Test | File | Asserts |
|------|------|---------|
| `test_is_missing_package_matches_expected_name` | `tests/test_scanner_init.py` | `_is_missing_package(ImportError(name="llm_guard"), {"llm_guard"})` returns `True` |
| `test_is_missing_package_rejects_unexpected_name` | `tests/test_scanner_init.py` | `_is_missing_package(ImportError(name="torch"), {"llm_guard"})` returns `False` |
| `test_is_missing_package_rejects_none_name` | `tests/test_scanner_init.py` | `_is_missing_package(ImportError("broken"), {"llm_guard"})` returns `False` |
| `test_broken_extra_reraises` | `tests/test_scanner_init.py` | Patching `petasos.scanners.llm_guard` to raise `ImportError(name="torch")` re-raises through `__init__.py` |
| `test_missing_extra_swallows_silently` | `tests/test_scanner_init.py` | Patching import of `llm_guard` to raise `ImportError(name="llm_guard")` results in `LlmGuardScanner` absent from `__all__` |
| `test_missing_extra_logs_debug` | `tests/test_scanner_init.py` | Same as above but capturing log output at DEBUG level confirms message is emitted |
| `test_transitive_dep_failure_reraises` | `tests/test_scanner_init.py` | If `llm_guard` imports fine but internally `import torch` fails (name="torch"), the `ImportError` propagates |
| `test_minimal_always_present` | `tests/test_scanner_init.py` | `MinimalScanner` is always in `__all__` regardless of extras availability |

## Decisions Carried Forward

- **`debug` level, not `warning`.** Missing extras are a normal deployment scenario (`pip install petasos` without extras). Warning-level logging would create noise for the base-install case. Operators who need to diagnose missing scanners can set `petasos.scanners` to DEBUG.
- **Helper function, not inline checks.** The `_is_missing_package()` helper is independently testable, reduces duplication across three blocks, and documents the security-relevant logic in one place.
- **No submodule matching.** The helper checks `exc_name in expected_names` for exact top-level package names only. A failure in `llm_guard.submodule` will have `name="llm_guard.submodule"`, which does not match `"llm_guard"`, so it correctly re-raises. This is the tightest possible guard.
- **Bare ImportError always re-raises.** `ImportError("message")` without `name=` is never a "package not found" — it is always an internal failure that should propagate.

## Done When

- [ ] `_is_missing_package()` helper extracted and used in all three import blocks
- [ ] `_logger.debug()` emitted on every swallowed ImportError
- [ ] Bare `ImportError("message")` (no `name`) re-raises in all three blocks
- [ ] `ImportError(name="unexpected_module")` re-raises in all three blocks
- [ ] All 8 tests listed above pass
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of Scope

- Runtime scanner health monitoring / heartbeat (tracked separately in pipeline orchestration)
- Auto-installation of missing extras (not appropriate for a security library)
- `__init__.py` as a scanner registry with dynamic discovery (current static imports are sufficient)
- Drawbridge backport (Drawbridge uses a different pattern; its own ticket if needed)
