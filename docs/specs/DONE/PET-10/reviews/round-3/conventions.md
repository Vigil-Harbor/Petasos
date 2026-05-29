# PET-10 Conventions Review — Round 3

**Spec:** `docs/specs/TODO/PET-10.spec.md`
**Brief:** `docs/briefs/PET-10-jwt-license-premium-wiring.md`
**Round:** 3

---

## Closure of Round 2 Findings

| Finding | Status | Evidence |
|---------|--------|----------|
| R2/F-1 (P2) wiki architecture.md and state.md | CLOSED | Deferred item 9 expanded to include all sources |
| R2/F-2 (P3) _DEFAULT_VALIDATOR singleton | CLOSED | Deferred item 7 |
| R2/F-3 (P2) LicenseValidator not in petasos/__init__.py | CLOSED | Design §4 now includes LicenseValidator |
| R2/F-4 (P3) Hatch build auto-discovery | CLOSED | Advisory — precedent exists |
| R2/F-5 (P2) tri-state test for licensed+feature-off | CLOSED | Test plan items 35-36 |
| R2/F-6 (P2) wiki files need update | CLOSED | Deferred item 9 |

## Findings

### F-1 — Scope table line 27 omits LicenseValidator from __init__.py additions (P2)

Same as correctness F-2. Design §4 is authoritative and includes it; scope table line 27 should list it for completeness. Advisory — implementer follows Design §4.

### F-2 — README.md also references `activate()` signature (P3)

Deferred item 5 mentions CLAUDE.md, and deferred item 9 mentions wiki files, but README.md may also document the `activate()` API. Should be included in post-ship update list.

### F-3 — pyproject.toml mypy override merge instruction could be more explicit (P3)

Design §6 says "Merge into the existing `[[tool.mypy.overrides]]` block" but doesn't specify whether to add `jwt` to the existing module list or create a new entry with `ignore_missing_imports = true`. The existing block may use different settings. Minor — implementer will read the current block.

### F-4 — LicenseValidator silently added to premium/__init__.py without test coverage (P3)

Test plan doesn't include an import test for `from petasos.premium import LicenseValidator`. Existing convention tests verify other premium re-exports. Low risk — any import failure would surface immediately.

### F-5 — Test plan item 42 fixture pattern not specified (P4)

Item 42 says "Create shared conftest.py fixtures" but doesn't specify fixture names or the JWT generation approach. Implementer will design the fixture — this is appropriate delegation.

STATUS: GREEN
