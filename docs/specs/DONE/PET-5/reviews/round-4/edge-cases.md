# PET-5 Spec Review — Edge Cases (Round 4)

**Spec:** `docs/specs/TODO/PET-5.spec.md` (v4)
**Brief:** `docs/briefs/PET-5-presidioscanner-brief.md`
**Reviewer:** spec-reviewer-edge-cases
**Round:** 4

---

## Closure of round 3 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | Manual-path overlapping findings produce corrupted output | CLOSED | spec lines 198-199: overlap resolution algorithm with confidence tiebreaker |
| F-2 | Manual-path uses `matched_text` which can be `None` | CLOSED | spec lines 200-201, 250-251: matched-text recovery with `text[start:end]` fallback |
| F-3 | Replace counter numbering ambiguity | CLOSED | spec lines 241-242: explicit increment-then-use with `_1`, `_2` examples |
| F-4 | Entity type recovery should replace hyphens with underscores | CLOSED | spec line 171: hyphens replaced with underscores in recovery |
| F-5 | No test for empty text input | CLOSED | spec line 314: `scan("")` and `anonymize("", [])` tests added |
| F-6 | No test for all-unpositioned findings | CLOSED | spec line 310: all-unpositioned findings test added |
| F-7 | Concurrent `scan()` on same instance | CLOSED | spec lines 103-104: threading.Lock on instance; Deferred line 382 |
| F-8 | `score_threshold` edge: threshold exactly equal to score | CLOSED | Deferred line 383: documents `>=` (inclusive) semantics |
| F-9 | Replace counter reset across calls | CLOSED | spec line 242: counter is local to each call |

---

## Findings

### F-1 (P3) — Overlap resolution tiebreaker underspecified for equal confidence and span length

Two overlapping findings with identical confidence and identical span length — spec's two-level tiebreaker is exhausted. Add a final tiebreaker: keep the first finding encountered (stable sort order).

### F-2 (P3) — Chain-overlapping findings: sliding-window behavior not specified

Three findings A=[0,10], B=[5,20], C=[15,25]: after resolving A-vs-B, does the winner become the new "current" for comparison with C? Spec should clarify "maintain a 'current' winning finding" for the sweep.

### F-3 (P3) — Non-Presidio findings with position get fabricated entity types

MinimalScanner findings with position data get entity types derived from rule_id suffix (e.g., `ROLE_SWITCH_CAPABILITY`). Functionally harmless but cosmetically odd. Spec says "best-effort" — acknowledged.

### F-4 (P2) — Mask mode: matched_text length vs position span mismatch

If `matched_text` length differs from `(end - start)`, the splice replaces position-span characters but the mask is computed from `matched_text` length. Consider always using `text[start:end]` for mask computation since the splice operates on position boundaries.

### F-5 (P3) — `anonymize()` raises ImportError — inconsistent with "pipeline never throws"

Spec documents this as a "safety net" with PET-6 responsible for catching. Informational — PET-6 must catch ImportError.

### F-6 (P3) — Engine path does not restate it operates on filtered findings

Readability issue — add parenthetical "Convert filtered findings (from step 2, all with position data) to Presidio RecognizerResult objects..."

---

STATUS: GREEN P0=0 P1=0 P2=1 P3=5
