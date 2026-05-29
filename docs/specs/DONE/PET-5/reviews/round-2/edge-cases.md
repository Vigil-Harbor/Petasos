# PET-5 Spec Review — Edge Cases (Round 2)

**Spec:** `docs/specs/TODO/PET-5.spec.md` (v2)
**Brief:** `docs/briefs/PET-5-presidioscanner-brief.md`
**Reviewer:** spec-reviewer-edge-cases
**Round:** 2

---

## Closure of round 1 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | Empty text input | OPEN (P2) | not addressed |
| F-2 | Very large text input | OPEN (P2) | not addressed |
| F-3 | Custom entity list validation | OPEN (P2) | not addressed |
| F-5 | score_threshold not plumbed | CLOSED | spec lines 130-143 show explicit analyze() call |
| F-6 | Non-Presidio findings | CLOSED | spec lines 166-167 handle recovery |
| F-7 | Empty hash_key string | OPEN (P3) | not addressed |
| F-8 | Mask formula data leak | CLOSED | spec lines 218-224 fix formula |
| F-10 | Filter before sort | CLOSED | spec line 165 filters first |
| F-11 | Concurrent scan() | OPEN (P4) | unchanged |

---

## Findings

### F-1 (P1) — Mask mode per-finding `chars_to_mask` incompatible with Presidio per-entity-type API

Same root cause as correctness F-2. Presidio's `operators` dict is keyed by entity type. Two PERSON findings of different lengths ("Jo" vs "Alexander Hamilton") need different `chars_to_mask` values but receive the same `OperatorConfig`.

### F-2 (P1) — Replace mode counter labels incompatible with per-entity-type API

Same root cause. `<PERSON_1>` and `<PERSON_2>` require different `new_value` per finding of the same entity type. Cannot express through a single `OperatorConfig`.

### F-3 (P2) — `AnonymizerEngine.anonymize()` returns `EngineResult`, not `str`

The spec's `anonymize()` returns `str` but Presidio's engine returns `EngineResult`. Need to extract `.text`.

### F-4 (P2) — Module-level `_module_anonymizer` cache not thread-safe

No lock around lazy initialization. TOCTOU race if two threads hit `anonymize()` concurrently. `add_anonymizer()` could be missed.

### F-5 (P2) — `add_anonymizer()` double registration on repeated calls

If `anonymize()` is called with `hash_key` then without, the operator is already registered. Need to confirm idempotency or guard.

### F-6 (P3) — Redact uses `Replace` operator, not Presidio's `Redact`

Semantically correct but could confuse implementers. Add a note.

### F-7 (P3) — No test for all-unpositioned findings

Test plan covers mixed but not all-unpositioned case.

### F-8 (P3) — `_ensure_loaded()` claims "PET-3/PET-4" but PET-4 differs

Same as correctness F-5.

### F-9 (P3) — `validate()` doesn't check `hmac_key` type

Could get `AttributeError` if non-string passed.

### F-10 (P3) — No test for empty text

`anonymize("", [])` and `scan("")` behavior not tested.

---

STATUS: RED P0=0 P1=2 P2=3 P3=5
