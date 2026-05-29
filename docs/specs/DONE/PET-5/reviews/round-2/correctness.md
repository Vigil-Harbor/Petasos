# PET-5 Spec Review — Correctness (Round 2)

**Spec:** `docs/specs/TODO/PET-5.spec.md` (v2)
**Brief:** `docs/briefs/PET-5-presidioscanner-brief.md`
**Reviewer:** spec-reviewer-correctness
**Round:** 2

---

## Closure of round 1 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | `_HmacSha256Operator` missing abstract methods | CLOSED | spec lines 187-203: all four methods shown |
| F-2 | Entity type recovery unspecified | CLOSED | spec lines 166-167: prefix-stripping + uppercasing documented |
| F-3 | `_ensure_loaded()` return vs raise | CLOSED | spec lines 83-84, 96-100: raises, scan() catches |
| F-4 | spaCy vs import error control flow | CLOSED | spec lines 83-88: ordered (import first, then engine) |
| F-5 | AnonymizerEngine masks analyzer-only install | OPEN (P2) | spec bundles both imports with single error message |
| F-6 | Done-when duplication | CLOSED | duplicate removed |
| F-7 | Mask table phrasing | CLOSED | table now says "Leading chars masked" |
| F-8 | Replace counter initial value | CLOSED | examples show 1-indexed |
| F-9 | score_threshold testing | OPEN (P3) | test plan lacks threshold-specific test |
| F-10 | Hash output length | OPEN (P3) | not specified |

---

## Findings

### F-1 (P1) — `_HmacSha256Operator` uses `@classmethod` but Presidio ABC declares instance methods

The spec declares `operator_name` and `operator_type` as `@classmethod` methods. Presidio's `Operator` ABC defines them as plain `@abstractmethod` instance methods. `mypy --strict` will flag incompatible override signatures. Change to instance methods with `self`.

### F-2 (P1) — Per-finding mask/replace behavior incompatible with Presidio's per-entity-type operators dict

Presidio's `AnonymizerEngine.anonymize()` takes `operators: Dict[str, OperatorConfig]` keyed by entity type. Mask mode needs different `chars_to_mask` per finding. Replace mode needs different `new_value` per finding. A single `OperatorConfig` per entity type cannot express this. The spec must specify a strategy: manual string replacement for mask/replace, custom stateful operators, or per-finding engine calls.

### F-3 (P2) — Anonymize behavior list numbering skip (1, 2, 4, 5)

Item 3 is missing from the numbered list — jumps from 2 to 4.

### F-4 (P2) — Mask mode example typo: `John Smith` → `******ith` should be `******mith`

10 chars - 4 visible = 6 masked. Last 4 chars of "John Smith" are "mith", not "ith".

### F-5 (P2) — `_ensure_loaded()` convention claim says "PET-3/PET-4" but PET-4 uses a different pattern

PET-4's `_ensure_loaded()` returns `bool` and stores errors in `self._load_error`. PET-5 matches PET-3 only. Change "PET-3/PET-4" to "PET-3".

### F-6 (P2) — `operate()` signature makes `params` required, ABC declares it optional

The spec's `operate(self, text, params: dict[str, Any])` omits the `= None` default that Presidio's ABC uses. `mypy --strict` may flag this. Add `| None = None` with a guard.

### F-7 (P3) — Plane ticket not cached in MCP memory

`memory_search` for PET-5 returned 0 results. Proceeded with brief.

---

STATUS: RED P0=0 P1=2 P2=4 P3=1
