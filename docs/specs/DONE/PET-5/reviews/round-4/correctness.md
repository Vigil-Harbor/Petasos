# PET-5 Spec Review — Correctness (Round 4)

**Spec:** `docs/specs/TODO/PET-5.spec.md` (v4)
**Brief:** `docs/briefs/PET-5-presidioscanner-brief.md`
**Reviewer:** spec-reviewer-correctness
**Round:** 4

---

## Closure of round 3 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | `entities` "DEFAULT" misleading | CLOSED | spec line 92: defaults to `None`, "all built-in entity types"; no mention of "DEFAULT" string |
| F-2 | Top-level `petasos/__init__.py` re-export diverges from PET-3 | CLOSED | spec lines 44-45: "The top-level `petasos/__init__.py` is **not** modified" |
| F-3 | Presidio Hash random salt non-determinism | CLOSED | spec lines 178-179: explicitly documents non-determinism of plain hash mode |
| F-4 | `score_threshold` testing gap | CLOSED | spec line 318: test added for `score_threshold=0.9` filtering |

---

## Findings

### F-1 (P2) — Entity type recovery example uses hyphenated `us-ssn` but encoding produces underscored `us_ssn`

Spec line 113: `rule_id = f"petasos.presidio.{entity_type.lower()}"` — `"US_SSN".lower()` produces `"us_ssn"` (underscores), not `"us-ssn"` (hyphens). But line 171 example shows `"petasos.presidio.us-ssn"` with a hyphen. The recovery code works regardless (uppercasing `us_ssn` gives `US_SSN`, hyphen replacement is a no-op), but the example is misleading. Change example to `"petasos.presidio.us_ssn"` → `"US_SSN"`.

### F-2 (P3) — Plane ticket PET-5 not cached in MCP memory

`memory_search` for PET-5 returned 0 results. Non-blocking — brief is source of truth.

---

STATUS: GREEN
