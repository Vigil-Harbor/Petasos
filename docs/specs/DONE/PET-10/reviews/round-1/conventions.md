# PET-10 Conventions Review — Round 1

**Spec:** `docs/specs/TODO/PET-10.spec.md`
**Brief:** `docs/briefs/PET-10-jwt-license-premium-wiring.md`
**Round:** 1

---

## Findings

### F-1 — CLAUDE.md divergence: `petasos.activate(key)` vs instance method (P2)

**Severity:** P2
**Section:** CLAUDE.md, Design §3

CLAUDE.md says "the public API is `petasos.activate(key)`" but the spec's actual design has `activate(key)` as an instance method on `Pipeline`, not a module-level function. The module-level export is `validate_license(key)` which only checks validity without activating. CLAUDE.md should be updated post-PET-10.

---

### F-4 — `petasos/premium/__init__.py` not listed for re-exports (P2)

**Severity:** P2
**Section:** Scope → Files to change

The existing `petasos/premium/__init__.py` re-exports from premium submodules. Adding `license.py` to the premium package means `premium/__init__.py` should also re-export `LicenseValidator`, `LicenseClaims`, `LicenseState`, and `validate_license` for consistency with how other premium modules are re-exported. Not listed in the scope table.

---

### F-6 — Module-level `validate_license` vs CLAUDE.md "Key Design Invariants" (P2)

**Severity:** P2
**Section:** Design §1, CLAUDE.md

CLAUDE.md's "Key Design Invariants" section says: "Premium enforcement is hot-unlock — `petasos.activate(key)` or `PETASOS_LICENSE_KEY` env var." The spec exports `validate_license(key)` at module level, which is a check-only function, not activation. The divergence between the documented public API and the actual exported API could confuse consumers. Should update CLAUDE.md after PET-10 ships.

---

### F-10 — Bare `assert` in `_check_premium` violates pipeline-never-throws (P1)

**Severity:** P1
**Section:** Design §3

The spec shows `assert self._license_claims is not None` inside `_check_premium()`. Bare `assert` statements can be stripped by `python -O`, and they violate the pipeline-never-throws invariant documented in CLAUDE.md ("Pipeline never throws — all errors caught and returned in PipelineResult"). This should be a defensive `if` guard that returns `False` and self-heals the state.

Consensus finding with edge-cases F-4.

---

### F-13 — mypy override should merge into existing block (P2)

**Severity:** P2
**Section:** Design §6 — `pyproject.toml` changes

The spec shows a separate `[[tool.mypy.overrides]]` block for `jwt`. The existing `pyproject.toml` already has a mypy overrides block for third-party libs. The new `jwt` module should be merged into the existing block's module list rather than adding a separate override section.

---

## Closure Table

| Finding | Status |
|---------|--------|
| F-1 | OPEN (P2 — advisory) |
| F-4 | OPEN (P2 — advisory) |
| F-6 | OPEN (P2 — advisory) |
| F-10 | OPEN |
| F-13 | OPEN (P2 — advisory) |

STATUS: RED P0=0 P1=1
