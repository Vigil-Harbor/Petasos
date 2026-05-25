# PET-5 · PresidioScanner Wrapper + Anonymization — Implementation Brief

> **Parent:** PET-2 (OSS Scanner Wrappers)
> **Phase:** 2 · **Blocked by:** PET-1 · **Blocks:** PET-6
> **Parallel with:** PET-3, PET-4
> **Spec traceability:** FR-1 (pluggable backends), FR-2 (PII detection and anonymization), NFR-4 (extras-based install)
> **File:** `petasos/scanners/presidio.py`
> **Extras:** `pip install petasos[presidio]` → `presidio-analyzer>=2.2,<3.0`, `presidio-anonymizer>=2.2,<3.0`

---

## Objective

Wrap Microsoft's [Presidio](https://github.com/microsoft/presidio) behind Petasos's `Scanner` protocol for PII detection, and expose a standalone `anonymize()` function for PII redaction. This is the only PET-2 child with **two responsibilities**: detection (scanner) and anonymization (utility consumed by PET-6's pipeline). Presidio v2.2.362 is current; the `>=2.2,<3.0` pin covers it.

---

## Decisions Carried Forward

### D1 — Two exports: `PresidioScanner` class + `anonymize()` function

The scanner detects PII and returns findings. It does **not** redact. The `anonymize()` function is a separate export that takes text + findings + mode and returns sanitized text. The pipeline (PET-6) calls `anonymize()` after merging all scanner findings — this keeps the scanner stateless and composable.

```python
# Detection (scanner protocol)
scanner = PresidioScanner()
result = await scanner.scan(text)

# Anonymization (pipeline utility, PET-6 consumes)
sanitized = anonymize(text, result.findings, mode="redact")
```

### D2 — Lazy-load both `presidio_analyzer` and `presidio_anonymizer`

Same pattern as PET-3/4. Both packages are imported inside `_ensure_loaded()` — a **new** lazy-load layer for optional deps extending MinimalScanner's try/except-in-scan pattern. If either import fails → errored `ScanResult`. The `anonymize()` function also lazy-loads `presidio_anonymizer` and raises `ImportError` if missing (this function is called by pipeline code that already verified the extra is installed, so the error is a safety net, not a normal path).

### D3 — RecognizerResult → ScanFinding mapping

Presidio's `AnalyzerEngine.analyze()` returns `list[RecognizerResult]`. Each has: `entity_type`, `start`, `end`, `score`. We map:

| Presidio field | Petasos field |
|---|---|
| `entity_type` | `ScanFinding.finding_type` = `"pii"`, `rule_id` = `f"petasos.presidio.{entity_type.lower()}"` |
| `start`, `end` | `ScanFinding.position` = `Position(start, end)` |
| `score` | `ScanFinding.confidence` |
| `text[start:end]` | `ScanFinding.matched_text` (the actual PII value — needed for anonymization) |

**Severity mapping by entity type:**

| Entity types | Severity |
|---|---|
| `CREDIT_CARD`, `IBAN_CODE`, `US_SSN`, `US_BANK_NUMBER`, `CRYPTO` | `CRITICAL` |
| `EMAIL_ADDRESS`, `PHONE_NUMBER`, `US_DRIVER_LICENSE`, `US_PASSPORT`, `IP_ADDRESS` | `HIGH` |
| `PERSON`, `LOCATION`, `DATE_TIME`, `NRP` | `MEDIUM` |
| All others | `LOW` |

### D4 — Presidio gives us span-level data (unlike PET-3/4)

This is Presidio's key advantage over LLM Guard and LlamaFirewall for pipeline integration. Every finding has precise `start`/`end` positions, which enables:
- Accurate dedup with overlapping findings from other scanners
- Position-aware anonymization (replace specific spans, not whole message)
- Audit trails with exact PII locations

### D5 — Anonymization modes

The `anonymize()` function supports four modes, matching the spec and Drawbridge's operator set:

| Mode | Behavior | Example |
|---|---|---|
| `"redact"` | Remove PII, replace with `<ENTITY_TYPE>` | `John` → `<PERSON>` |
| `"replace"` | Replace with synthetic value | `John` → `<PERSON_1>` (counter-based) |
| `"hash"` | HMAC-SHA256 hash of value | `John` → `a3f2b7...` (deterministic with key) |
| `"mask"` | Partial masking | `555-1234` → `***-1234` |

### D6 — HMAC-SHA256 for hash mode, not MD5

The spec mandates HMAC-SHA256 for redaction hashing (carried from Drawbridge). Presidio v2.2.358+ deprecated MD5 in favor of SHA256/SHA512, so we're aligned with upstream. The `anonymize()` function takes an optional `hash_key: str | None` parameter — when provided, uses HMAC-SHA256; when `None`, uses plain SHA256.

HMAC-SHA256 makes hashes **correlatable across sessions** (same PII + same key = same hash), which is required for premium audit trails. The key is injected by the pipeline, not stored in the scanner.

### D7 — Entity list defaults to `["DEFAULT"]`

Presidio's `"DEFAULT"` entity set covers ~20 common PII types (PERSON, EMAIL, PHONE, CREDIT_CARD, etc.). Users can narrow or expand via the `entities` constructor param. Passing specific entities reduces false positives and latency.

### D8 — Language defaults to English, single-language per scan

Presidio supports multi-language analysis but requires language-specific NLP models (spaCy). We default to `"en"` and run single-language analysis per scan call. Multi-language support is out of scope — it requires additional spaCy models and complicates the extras install.

### D9 — spaCy model dependency

Presidio requires a spaCy language model (`en_core_web_lg` for best accuracy, `en_core_web_sm` for speed). This is **not** automatically installed by `pip install presidio-analyzer`. The `_ensure_loaded()` method checks for the model and provides a clear error message: `"spaCy model not found. Run: python -m spacy download en_core_web_lg"`. We do not auto-download models.

### D10 — `score_threshold` default is 0.35

Lower than typical ML thresholds because PII detection is recall-heavy — missing a credit card number is worse than a false positive on "John" as a person name. The spec and work items agree on 0.35.

### D11 — Anonymizer sorts findings by position

Presidio's `AnonymizerEngine` requires findings sorted by `start` position. The `anonymize()` function handles this internally — callers pass unsorted findings, we sort before applying operators. This is consistent with Presidio v2.2.362's internal behavior change (sorting analyzer results for correct whitespace merging).

### D12 — Platform: no subprocess concern

Presidio runs in-process (spaCy + regex recognizers). No subprocess spawning. Windows footgun does not apply.

---

## Done When

- [ ] `PresidioScanner` class in `petasos/scanners/presidio.py` implements the `Scanner` protocol
- [ ] Lazy-load pattern: `import presidio_analyzer` / `presidio_anonymizer` fails → returns errored `ScanResult`, no crash
- [ ] Constructor params: `entities`, `language`, `score_threshold`
- [ ] `RecognizerResult` → `ScanFinding` mapping with entity type, position, confidence, matched_text
- [ ] Severity mapping by entity type category (CRITICAL/HIGH/MEDIUM/LOW)
- [ ] `name` property returns `"presidio"`
- [ ] Duration tracking via `time.perf_counter`
- [ ] `anonymize(text, findings, mode, hash_key=None)` function exported
- [ ] Anonymization correct for all four modes: redact, replace, hash, mask
- [ ] HMAC-SHA256 hash mode produces deterministic, correlatable hashes (same input + key = same hash)
- [ ] Plain SHA256 fallback when no key provided
- [ ] Anonymizer handles overlapping/unsorted findings correctly
- [ ] Integration tests against real `presidio-analyzer` (not mocked) with 20-message corpus containing known PII
- [ ] `pip install petasos[presidio]` succeeds in clean Python 3.11 venv
- [ ] Fail-open verified under backend exception
- [ ] spaCy model missing → clear error message, no crash
- [ ] ≥20 tests passing (detection + anonymization)
- [ ] `mypy --strict` clean
- [ ] `ruff check` / `ruff format` clean

---

## Out of Scope

- **Multi-language PII detection** — English only. Additional spaCy models are a future enhancement.
- **Custom recognizers** — Presidio supports user-defined recognizers (regex, deny-lists, ML); we expose only the built-in set. Custom recognizer registration is future work.
- **LLM-based recognizers** — Presidio v2.2.362 added LangExtract-based PII detection (LLM/SLM). We use the traditional NLP pipeline. LLM recognizers are a future premium feature candidate.
- **Image PII detection** — Presidio has an image redactor module. Text-only for PET-5.
- **Deanonymization / reversible anonymization** — the `anonymize()` function is one-way. Presidio's `Deanonymize` operator is not exposed.
- **Pipeline integration** — PET-6 consumes this scanner and calls `anonymize()`.
- **Frequency, escalation, profiles** — premium tier (PET-7+).
- **Auto-download of spaCy models** — user must install manually. A future CLI `petasos setup` may address this.
