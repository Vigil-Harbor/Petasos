# PET-5 Spec Review — Edge Cases (Round 3)

**Spec:** `docs/specs/TODO/PET-5.spec.md` (v3)
**Brief:** `docs/briefs/PET-5-presidioscanner-brief.md`
**Reviewer:** spec-reviewer-edge-cases
**Round:** 3

---

## Closure of round 2 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | Mask mode per-finding `chars_to_mask` incompatible with Presidio API | CLOSED | spec lines 179-197: dual-path anonymization — mask uses manual path |
| F-2 | Replace mode counter labels incompatible with per-entity-type API | CLOSED | spec lines 179-197: replace uses manual path |
| F-3 | `anonymize()` returns `EngineResult`, not `str` | CLOSED | spec line 177: extracts `.text` from `EngineResult` |
| F-4 | Module-level `_module_anonymizer` cache not thread-safe | CLOSED | spec line 165: `threading.Lock` guards lazy init |
| F-5 | `add_anonymizer()` double registration | CLOSED | spec line 165: "idempotent — safe if called again" |
| F-6 | Redact uses `Replace` operator | CLOSED | spec line 185: explicitly shows `Replace(new_value=...)` |
| F-7 | No test for all-unpositioned findings | OPEN (P3) | test plan line 295 covers mixed but not all-unpositioned |
| F-8 | `_ensure_loaded()` claims "PET-3/PET-4" | CLOSED | spec line 102: fixed to PET-3 only |
| F-9 | `validate()` doesn't check `hmac_key` type | CLOSED | spec line 212: `isinstance(params.get("hmac_key"), str)` |
| F-10 | No test for empty text | OPEN (P3) | not in test plan |

---

## Findings

### F-1 (P1) — Manual-path overlapping findings produce corrupted output

The manual path (replace, mask) processes findings in reverse position order. If two findings have overlapping spans (e.g., `Position(5, 15)` and `Position(10, 20)`), the second replacement (in reverse order, so Position(10,20) first) modifies the text, then the first replacement (Position(5,15)) operates on now-shifted text. The engine path delegates overlap resolution to Presidio, but the manual path has no overlap handling.

Resolution: before applying manual-path replacements, deduplicate overlapping findings. For overlapping spans, keep the finding with the higher confidence (or the longer span as tiebreaker). Add this deduplication step to the manual-path description and a test case.

### F-2 (P1) — Manual-path uses `matched_text` which can be `None`

Per `_types.py`, `ScanFinding.matched_text` is typed `str | None = None`. The mask mode computes `len(matched_text)` — if `matched_text is None`, this raises `TypeError`. The replace mode also uses `matched_text` for display in some implementations. The manual path must fall back to `text[start:end]` when `matched_text is None`.

### F-3 (P2) — Replace counter numbering ambiguity

`defaultdict(int)` starts counters at 0. The spec examples show 1-indexed labels (`<PERSON_1>`, `<PERSON_2>`). The spec should clarify the increment-then-use ordering: increment the counter first, then format the label, so the first occurrence is `_1` not `_0`.

### F-4 (P2) — Entity type recovery should replace hyphens with underscores

Some entity types contain hyphens in their lowercased form (e.g., `US-SSN` → `petasos.presidio.us-ssn`). Uppercasing alone gives `US-SSN` but Presidio uses `US_SSN`. The recovery function should replace hyphens with underscores after uppercasing.

### F-5 (P3) — No test for empty text input

`scan("")` and `anonymize("", [])` behavior not tested. Should return empty results / unchanged empty string.

### F-6 (P3) — No test for all-unpositioned findings

If all findings passed to `anonymize()` have `position=None`, the function should return the original text unchanged. Not tested.

### F-7 (P3) — Concurrent `scan()` on same instance

Two concurrent `scan()` calls on the same `PresidioScanner` instance — `_ensure_loaded()` may run twice. Low risk since engine creation is idempotent, but worth noting.

### F-8 (P3) — `score_threshold` edge: threshold exactly equal to score

Presidio's `score_threshold` is `>=` (inclusive). Document whether our threshold follows the same semantics.

### F-9 (P4) — Replace counter reset across calls

Test plan mentions counter reset across calls but doesn't specify whether `anonymize()` state leaks between calls. Confirmed: `defaultdict(int)` is local to each call — no leakage.

---

STATUS: RED P0=0 P1=2 P2=2 P3=4 P4=1
