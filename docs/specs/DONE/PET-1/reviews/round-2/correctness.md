# PET-1 Spec Review — Correctness (Round 2)

**Spec:** `docs/specs/TODO/PET-1.spec.md`
**Brief:** `docs/briefs/PET-1-brief.md`
**Round:** 2

---

## Closure of round 1 findings

| Finding | Status | Evidence |
|---------|--------|----------|
| R1/F-1 (PipelineResult field name mismatch) | CLOSED | Spec v2 uses `scanner_results` consistently everywhere |
| R1/F-2 (to_dict() promised but never defined) | CLOSED | Method signatures added to ScanFinding (line 173-176) and ScanResult (line 185-188) |
| R1/F-3 (ScanFinding.findings typo) | CLOSED | Line 214 now reads `ScanResult.findings` |
| R1/F-4 (Homoglyph-substitution divergence) | CLOSED | Decision D6 (lines 82-85) acknowledges divergence with rationale |
| R1/F-5 (Suppression semantics underspecified) | CLOSED | Decision D7 (lines 87-93) covers all three edge cases |

---

## Findings

### F-1 [P1] `confusables_normalized` flag scoped narrower than Drawbridge without acknowledgement

The spec (line 314) says "Check if any substitutions were made to set `confusables_normalized`" in the context of Step 4 (homoglyph mapping only). Drawbridge's `normalize.ts` sets `confusablesNormalized = normalized !== stripped`, capturing BOTH NFKC and homoglyph changes. This means NFKC-only obfuscation (e.g., fullwidth Latin) would set the flag in Drawbridge but not in Petasos.

**Impact:** The `homoglyph-substitution` rule would not fire on NFKC-only evasion (fullwidth "ignore previous instructions"), even though the attack text becomes visible after normalization. Either widen the flag semantics or add a Decision acknowledging the narrower scope.

### F-2 [P2] D3 says all result types get `to_dict()` but only two of four do

D3 (line 71) names all four types but `PipelineResult` and `NormalizedText` code blocks lack `to_dict()`. Code blocks trump prose.

### F-3 [P2] Processing order step 5 says "normalization metadata" but base64 uses raw text

Step 5 (line 421): "Run encoding detection using normalization metadata" — but the base64 rule uses `re.search(..., text)` against raw input, not normalization metadata.

### F-4 [P3] INVISIBLE_CHARS missing U+2065 compared to Drawbridge range

Drawbridge uses `⁠-⁩` which includes U+2065 (reserved). The spec skips it. Low risk.

### F-5 [P3] Plane ticket not cached in MCP memory

MCP search returned zero results. Proceeding with brief as canonical source.

### F-6 [P4] Unused `field` import in `_types.py` code block

`from dataclasses import dataclass, field` — `field` is never used. Would trigger ruff F401.

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

STATUS: RED P0=0 P1=1 P2=2 P3=2 P4=1
