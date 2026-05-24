# PET-1 Spec Review — Correctness (Round 1)

**Spec:** `docs/specs/TODO/PET-1.spec.md`
**Brief:** `docs/briefs/PET-1-brief.md`
**Round:** 1

---

## Findings

### F-1 [P0] PipelineResult field name mismatch

The brief (§3.2) and spec prose (§2, "Key design choices") reference `scanner_metadata` as the field carrying per-scanner results. The actual code block for `PipelineResult` defines the field as `scanner_results`:

```python
scanner_results: tuple[ScanResult, ...] = ()
```

One name must win. The code block is the implementation source of truth — if `scanner_results` is the intended name, update the prose. If the brief's `scanner_metadata` is canonical, update the code block.

**Impact:** Implementer will choose one and downstream consumers (PET-6, PET-8) will see a different name in the prose, causing integration bugs.

### F-2 [P0] `to_dict()` methods promised but never defined

Decision D3 says "Provide `to_dict()` helpers for JSON serialization." The test plan includes:

- `ScanFinding.to_dict()` round-trips through JSON correctly
- `ScanResult.to_dict()` round-trips through JSON correctly

But the `_types.py` code blocks define no `to_dict()` method on any type. Frozen dataclasses don't get these for free — they must be explicitly written.

**Impact:** Test plan references methods that don't exist in the design. Either add the method signatures to the code blocks, or remove from the test plan and defer to PET-6.

### F-3 [P1] Typo: `ScanFinding.findings` should be `ScanResult.findings`

In the "Key design choices" section:

> `ScanFinding.findings` is `tuple`, not `list`

This should read `ScanResult.findings` — `ScanFinding` has no `findings` field. `ScanResult` is the type whose `findings` field is typed as `tuple[ScanFinding, ...]`.

### F-4 [P1] Homoglyph-substitution fires unconditionally — diverges from Drawbridge without acknowledgement

The spec's encoding rule `petasos.syntactic.encoding.homoglyph-substitution` fires whenever `normalized.confusables_normalized` is true. Drawbridge's source (`src/validation/index.ts`) gates the homoglyph-substitution rule on a conjunction: `confusablesNormalized AND injectionMatchedOnNormalized` — the rule only fires when homoglyphs co-occur with an injection pattern match.

The spec's unconditional approach will produce false positives on benign text containing legitimate Cyrillic or Greek characters. This is a valid design choice if acknowledged and justified, but the spec is silent on the divergence.

**Impact:** The brief says "Port Drawbridge's 17 syntactic rules" — an implementer reading both the Drawbridge source and this spec will see an unexplained behavioral difference. Either gate on co-occurrence (matching Drawbridge) or add a Decision note acknowledging the divergence and explaining why it's intentional.

### F-5 [P1] Suppression semantics underspecified

The `suppress_rules` parameter on `MinimalScanner.__init__()` is documented but the spec doesn't describe:
1. Whether suppression prevents the rule from *running* or just from *appearing in findings*
2. How suppression interacts with the invisible-chars escalation (if `invisible-chars` is suppressed, does the escalation logic still check for injection co-occurrence?)
3. What happens if a structural rule ID is passed in `suppress_rules` (the spec says `can_suppress=False` but doesn't say what happens — silent ignore? ValueError?)

These edge cases will be implementation decisions by default, leading to inconsistency across code and tests.

---

## Closure Table

| Finding | Status | Evidence |
|---------|--------|----------|
| F-1 | OPEN | — |
| F-2 | OPEN | — |
| F-3 | OPEN | — |
| F-4 | OPEN | — |
| F-5 | OPEN | — |

STATUS: RED P0=2 P1=3
