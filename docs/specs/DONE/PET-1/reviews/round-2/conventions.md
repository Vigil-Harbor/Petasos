# PET-1 Spec Review — Conventions (Round 2)

**Spec:** `docs/specs/TODO/PET-1.spec.md`
**Brief:** `docs/briefs/PET-1-brief.md`
**Round:** 2

---

## Closure of round 1 findings

| Finding | Status | Evidence |
|---------|--------|----------|
| R1/F-1 (Test command Windows path) | CLOSED | Deferred section line 588 |
| R1/F-2 (Single source of version) | CLOSED | Deferred section line 589 |
| R1/F-3 (ruff.toml unspecified) | CLOSED | Deferred section line 590 |

---

## Findings

### F-1 [P3] D6 is spec-level addition — human drift-check needed

Not in brief's D1-D5. Added by spec-cycle to address correctness review. Well-reasoned. Flagging for drift-check only.

### F-2 [P3] D7 is spec-level addition — human drift-check needed

Suppression semantics not in brief. Added to address correctness review. Well-specified. Flagging for drift-check only.

### F-3 [P3] PipelineResult placeholder is a spec-level scoping decision

Brief lists PipelineResult as full deliverable. Spec reduces to OSS-tier placeholder with rationale. Flagging for drift-check.

### F-4 [P4] SyntacticRule is an internal type not in brief

Minor implementation detail. Private, follows D3 convention.

### F-5 [P4] RULE_TAXONOMY export not in brief

Lightweight frozen export with documented downstream need (PET-8).

### F-6 [P4] `from_dict()` asymmetry across types

`ScanFinding`/`ScanResult` have `to_dict()`/`from_dict()` but `PipelineResult`/`NormalizedText` don't. Reasonable but undocumented.

---

## Closure Table

| Finding | Status | Evidence |
|---------|--------|----------|
| F-1 | OPEN | — |
| F-2 | OPEN | — |
| F-3 | OPEN | — |
| F-4 | OPEN | — |
| F-5 | OPEN | — |
| F-6 | OPEN | — |

STATUS: GREEN
