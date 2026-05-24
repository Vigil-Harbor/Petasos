# PET-1 Spec Review — Conventions (Round 1)

**Spec:** `docs/specs/TODO/PET-1.spec.md`
**Brief:** `docs/briefs/PET-1-brief.md`
**Round:** 1

---

## Findings

### F-1 [P2] Test command hardcodes Windows-specific Python path

The test command section specifies:

```bash
C:\Users\zioni\AppData\Local\Programs\Python\Python311\python.exe -m pytest tests/ -v --tb=short
```

This is appropriate for the primary developer's machine, but CI (GitHub Actions on `ubuntu-latest`) will use a different Python path. The spec should note that CI uses `python -m pytest` while the local command uses the pinned Windows path.

**Impact:** Low — CI config will naturally use the right path. But spec readers may be confused by the OS-specific path without context.

### F-2 [P2] Missing `__version__` in `_types.py` vs `__init__.py`

The `__init__.py` code block defines `__version__ = "0.0.1"` and the `pyproject.toml` also sets `version = "0.0.1"`. This is fine for now, but the spec doesn't mention a single-source-of-version strategy (e.g., `hatch-vcs`, `importlib.metadata`, or manual sync). Consider noting the version source of truth.

### F-3 [P2] `ruff.toml` not specified

The scope lists `ruff.toml` as a file to create, but the design section doesn't specify its contents. The implementer will need to decide rule selection, line length, target Python version, etc. This is a minor gap since ruff defaults are reasonable.

---

## Closure Table

| Finding | Status | Evidence |
|---------|--------|----------|
| F-1 | OPEN | — |
| F-2 | OPEN | — |
| F-3 | OPEN | — |

STATUS: GREEN
