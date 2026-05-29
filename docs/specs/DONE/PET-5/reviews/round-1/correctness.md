# PET-5 Spec Review — Correctness (Round 1)

**Spec:** `docs/specs/TODO/PET-5.spec.md`
**Brief:** `docs/briefs/PET-5-presidioscanner-brief.md`
**Reviewer:** spec-reviewer-correctness
**Round:** 1

---

## Findings

### F-1 (P1) — `_HmacSha256Operator` missing required abstract methods

The spec shows `_HmacSha256Operator(Operator)` with only `operate()` defined. Presidio's `Operator` ABC requires three additional abstract methods:
- `validate(params)` — validates operator parameters
- `operator_name()` — returns operator name string (class method)
- `operator_type()` — returns `OperatorType.Anonymize` (class method)

Without these, `_HmacSha256Operator` cannot be instantiated — Python raises `TypeError` for unimplemented abstract methods. The spec must expand the code block to include all four required methods.

**Impact:** Implementation will fail at runtime if the spec is followed as-is.

### F-2 (P1) — Entity type recovery from ScanFinding not specified for anonymize()

The `anonymize()` function converts `ScanFinding` back to `RecognizerResult`, which requires an `entity_type` field. `ScanFinding` does not have an `entity_type` field — the entity type is encoded in `rule_id` (e.g., `petasos.presidio.person`). The spec does not describe how the function recovers the entity type.

The recovery mechanism should be: strip the `petasos.presidio.` prefix from `rule_id` and uppercase the remainder. This needs to be explicitly documented in the Finding Conversion section.

**Impact:** Implementer must guess the entity type recovery logic, risking inconsistency.

### F-3 (P2) — `_ensure_loaded()` dual responsibility ambiguity

The Design section says `_ensure_loaded()` returns an errored `ScanResult` on import failure, but the conventions of PET-3/PET-4 have `_ensure_loaded()` raising and `scan()` catching. The spec should clarify whether `_ensure_loaded()` returns or raises.

### F-4 (P2) — spaCy error vs import error conflation

The spec describes two different error messages for `_ensure_loaded()`: one for import failure ("presidio not installed") and one for spaCy model missing. But it doesn't specify the control flow — does the method try the import first, then engine construction? Or are these separate try/except blocks? The ordering matters for the error message.

### F-5 (P2) — AnonymizerEngine in _ensure_loaded may mask analyzer-only install

If a user installs `presidio-analyzer` but not `presidio-anonymizer`, `_ensure_loaded()` will fail with a generic "presidio not installed" message. The spec could differentiate: analyzer missing vs anonymizer missing.

### F-6 (P2) — Done-when item 19 duplicates item 3

"spaCy model missing -> clear error message, no crash" appears in both done-when items 3 (line 262) and 20 (line 280).

### F-7 (P3) — Operator mapping table says "from end" but prose says "leading"

The mask operator table row says `chars_to_mask` "from end" combined with `from_end=False`, which is contradictory phrasing. The intent (mask leading chars) is clear from prose but the table is confusing.

### F-8 (P3) — Replace counter scope not fully specified

The spec says counters are scoped per entity type within a single `anonymize()` call, but doesn't specify the initial counter value (0 or 1). The example shows `<PERSON_1>`, implying 1-indexed.

### F-9 (P3) — Test plan doesn't specify score_threshold testing

The brief mandates `score_threshold=0.35` as the default. The test plan doesn't include a test that verifies this default produces expected recall on the 20-message corpus.

### F-10 (P3) — hash mode output length not specified

The spec says HMAC-SHA256 produces a hex digest but doesn't specify the expected length (64 hex chars for SHA256). Not strictly required but useful for test assertions.

---

STATUS: RED P0=0 P1=2 P2=4 P3=4
