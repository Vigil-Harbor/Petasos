# PET-5 Spec Review — Conventions (Round 1)

**Spec:** `docs/specs/TODO/PET-5.spec.md`
**Brief:** `docs/briefs/PET-5-presidioscanner-brief.md`
**Reviewer:** spec-reviewer-conventions
**Round:** 1

---

## Findings

### F-1 (P2) — `_ensure_loaded()` return vs raise convention

The spec says `_ensure_loaded()` "returns an errored ScanResult" on import failure. PET-3 and PET-4 briefs describe `_ensure_loaded()` as a method that raises/fails, with the `scan()` method catching the error and producing the errored `ScanResult`. The spec should align with the sibling scanners: `_ensure_loaded()` raises on failure, `scan()` catches and wraps.

This isn't a correctness issue (either approach works), but it's a conventions divergence that makes the codebase inconsistent across PET-3/4/5.

### F-2 (P2) — Re-export pattern missing try/except conditional import

The Scope section says `petasos/scanners/__init__.py` will re-export `PresidioScanner` and `anonymize`. But since `presidio.py` lazy-loads its dependencies, the re-export should use a try/except conditional import pattern so that `from petasos.scanners import PresidioScanner` doesn't fail when presidio extras aren't installed. PET-3 brief mentions this pattern.

### F-3 (P3) — Doc style for severity map

The severity mapping is well-documented in the spec. CLAUDE.md says "default to writing no comments" in code, but a module-level constant like `_SEVERITY_MAP` benefits from a one-line comment explaining the tiers. This is consistent with MinimalScanner's `RULE_TAXONOMY` which has a brief docstring.

### F-4 (P3) — Test file naming convention

`tests/test_presidio_scanner.py` follows the established pattern from `tests/test_minimal_scanner.py`. Consistent.

### F-5 (P2) — Dual AnonymizerEngine instantiation sites

The spec creates `AnonymizerEngine` in `_ensure_loaded()` (cached on `self._anonymizer`) AND the `anonymize()` standalone function lazy-loads its own `AnonymizerEngine`. This means two separate engine instances exist. The spec should clarify whether the standalone `anonymize()` creates its own module-level cached engine, or whether there's a shared engine. Since `anonymize()` is a standalone function (not a method), it can't access `self._anonymizer`. A module-level `_anonymizer_engine` cache would be the natural pattern.

### F-6 (P3) — asyncio.to_thread usage matches PET-4

PET-4 brief establishes the `asyncio.to_thread()` pattern for wrapping synchronous scanner calls. PET-5 follows the same convention. Consistent.

### F-7 (P3) — Error message format

The spec uses `error="presidio not installed. pip install petasos[presidio]"` which matches the pattern from PET-3 (`"llm-guard not installed. pip install petasos[llm-guard]"`). Consistent.

### F-8 (P4) — Spec date accuracy

Spec header shows `Date: 2026-05-24` which is today's date. Correct.

### F-9 (P4) — pyproject.toml extras already defined

Spec correctly identifies that `pyproject.toml` already has the presidio extras defined and lists it under "Files to leave alone." Good awareness.

---

STATUS: GREEN
