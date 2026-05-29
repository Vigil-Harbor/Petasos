# PET-5 — PresidioScanner Wrapper + Anonymization

> **Spec version:** v4 (revised round 3)
> **Brief:** `docs/briefs/PET-5-presidioscanner-brief.md`
> **Plane:** PET-5, project `5bff6316-84ea-4103-b9e2-4861ac9c226a`
> **Author:** Claude (spec-cycle)
> **Date:** 2026-05-24
> **Parent:** PET-2 (OSS Scanner Wrappers)
> **Blocked by:** PET-1 (landed)
> **Blocks:** PET-6 (Pipeline Orchestration)
> **Parallel with:** PET-3, PET-4

---

## Goal

Implement the `PresidioScanner` wrapper and a standalone `anonymize()` function in `petasos/scanners/presidio.py`. This is the only PET-2 child with two responsibilities: PII detection (via `presidio-analyzer`) and PII anonymization (via `presidio-anonymizer`). The scanner maps Presidio's span-level `RecognizerResult` objects to Petasos's `ScanFinding` type — including exact `Position` data, which PET-3 and PET-4 cannot provide. The `anonymize()` function is a separate export consumed by the pipeline (PET-6) after finding merge; it supports four operator modes (redact, replace, hash, mask) with HMAC-SHA256 hashing for audit correlation.

---

## Scope

### Files to create

```
petasos/scanners/presidio.py           # PresidioScanner class + anonymize() function
tests/test_presidio_scanner.py         # Unit + integration tests (≥20)
```

### Files to modify

```
petasos/scanners/__init__.py           # Conditional re-export: try/except ImportError around PresidioScanner, anonymize
```

Re-exports use a try/except conditional import so that `from petasos.scanners import PresidioScanner` does not fail when presidio extras are not installed. Pattern (matching PET-3):
```python
try:
    from petasos.scanners.presidio import PresidioScanner, anonymize
    __all__ += ["PresidioScanner", "anonymize"]
except ImportError:
    pass
```

`__all__` entries are appended inside the try block so they are only exported when the import succeeds. The top-level `petasos/__init__.py` is **not** modified — matching PET-3's convention where scanner re-exports live only in `petasos/scanners/__init__.py`.

### Files to leave alone

- `petasos/_types.py` — types are sufficient as-is (`ScanFinding.position`, `ScanFinding.matched_text` already exist)
- `petasos/normalize.py` — no changes needed
- `petasos/scanners/minimal.py` — no changes needed
- `pyproject.toml` — `presidio` extras already defined (`presidio-analyzer>=2.2,<3.0`, `presidio-anonymizer>=2.2,<3.0`)
- `petasos-spec.md`, `petasos-work-items.md` — project docs, not code

---

## Design

### PresidioScanner class

```python
class PresidioScanner:
    def __init__(
        self,
        *,
        entities: list[str] | None = None,
        language: str = "en",
        score_threshold: float = 0.35,
    ) -> None: ...

    @property
    def name(self) -> str:
        return "presidio"

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult: ...
```

The class satisfies the `Scanner` protocol from `petasos._types`. Key behaviors:

1. **Lazy-load pattern.** Presidio dependencies (`presidio_analyzer`, `presidio_anonymizer`) are imported inside a private `_ensure_loaded()` method, called on first `scan()`. If either import fails, `_ensure_loaded()` **raises** `ImportError`. The `scan()` method catches this and returns an errored `ScanResult` with `error="presidio not installed. pip install petasos[presidio]"` and empty findings — it does **not** propagate. This matches the PET-3 convention: `_ensure_loaded()` raises, `scan()` catches and wraps.

2. **spaCy model check.** After successfully importing `presidio_analyzer`, `_ensure_loaded()` instantiates `AnalyzerEngine()`. If the spaCy model is missing, Presidio raises at engine construction time. `_ensure_loaded()` lets this propagate; `scan()` catches it and returns an errored `ScanResult` with `error="spaCy model not found. Run: python -m spacy download en_core_web_lg"`. The scanner does not auto-download models.

3. **Engine reuse.** The `AnalyzerEngine` and `AnonymizerEngine` are instantiated once in `_ensure_loaded()` and cached on the instance (`self._analyzer`, `self._anonymizer`). Subsequent `scan()` calls reuse the cached engines.

4. **Entity list.** Constructor parameter `entities` defaults to `None`. When `None`, `analyzer.analyze()` detects all built-in entity types (~20 common PII types). Callers can narrow (e.g., `["PERSON", "EMAIL_ADDRESS"]`) or expand (specific entity types). The value is stored as `self._entities` and passed to `analyzer.analyze()` — `None` means "all entities."

5. **Duration tracking.** Uses `time.perf_counter()` before and after the scan body, same pattern as `MinimalScanner`.

6. **Error isolation.** The entire `scan()` body is wrapped in try/except. Any exception from Presidio produces an errored `ScanResult` with the exception message. The "pipeline never throws" invariant is preserved.

### Decision: `_ensure_loaded()` instantiates both engines, raises on failure

Both `AnalyzerEngine` and `AnonymizerEngine` are created together in `_ensure_loaded()`, even though the scanner itself only uses the analyzer. Rationale: the `anonymize()` function needs the anonymizer engine, and it makes sense to fail fast on load rather than discover a broken install at anonymization time. The `AnonymizerEngine` is lightweight (no model loading) — the cost is trivial.

`_ensure_loaded()` raises on any failure (import error, spaCy model missing). It does not return `ScanResult` — that is `scan()`'s responsibility. On the first failure, the error is cached (e.g., in `self._load_error`); subsequent calls re-raise the cached error without re-attempting the import. This catch-cache-reraise pattern matches PET-3's convention. (PET-4 uses a different pattern — `_ensure_loaded()` returns `bool` with errors cached in `self._load_error`.)

`_ensure_loaded()` is guarded by a `threading.Lock` on the instance (`self._load_lock`, initialized in `__init__`). This prevents TOCTOU races when `asyncio.to_thread()` schedules concurrent `scan()` calls on different threads — matching PET-3's concurrency-safe lazy-load pattern.

### RecognizerResult → ScanFinding mapping

Each `RecognizerResult` from Presidio maps to a `ScanFinding`:

| Presidio field | Petasos field | Notes |
|---|---|---|
| `entity_type` | `finding_type = "pii"` | All PII findings share this type |
| `entity_type` | `rule_id = f"petasos.presidio.{entity_type.lower()}"` | e.g., `petasos.presidio.person` |
| `start`, `end` | `position = Position(start, end)` | Exact span — Presidio's key advantage |
| `score` | `confidence` | Presidio's 0.0–1.0 score |
| `text[start:end]` | `matched_text` | The actual PII value |
| (derived) | `severity` | See severity mapping below |
| (fixed) | `scanner_name = "presidio"` | |
| (derived) | `message` | `f"PII detected: {entity_type}"` |

### Decision: severity mapping by entity type category

Entity types are grouped into severity tiers based on data sensitivity and regulatory impact:

| Severity | Entity types |
|---|---|
| `CRITICAL` | `CREDIT_CARD`, `IBAN_CODE`, `US_SSN`, `US_BANK_NUMBER`, `CRYPTO` |
| `HIGH` | `EMAIL_ADDRESS`, `PHONE_NUMBER`, `US_DRIVER_LICENSE`, `US_PASSPORT`, `IP_ADDRESS` |
| `MEDIUM` | `PERSON`, `LOCATION`, `DATE_TIME`, `NRP` |
| `LOW` | All others (unlisted entity types) |

The mapping is implemented as a module-level `dict[str, Severity]` constant (`_SEVERITY_MAP`). Unknown entity types default to `LOW`. This is a frozen lookup — the map is not configurable per-instance (profile-driven severity overrides are PET-8 scope).

### Decision: constructor params plumbed to analyze() call

The constructor stores `score_threshold` as `self._score_threshold` and `language` as `self._language`. Both are passed explicitly to every `analyzer.analyze()` call:

```python
results = self._analyzer.analyze(
    text=text,
    entities=self._entities,
    language=self._language,
    score_threshold=self._score_threshold,
)
```

Without passing `score_threshold`, Presidio uses its own default (0.0 in v2.2), which would flood the output with low-confidence noise. The brief mandates 0.35 as the default — high recall, tolerable false-positive rate.

### Decision: scan runs synchronously via asyncio.to_thread

Presidio's `AnalyzerEngine.analyze()` is a synchronous call that runs spaCy NLP + regex recognizers. Unlike PET-4's LlamaFirewall (which does ML inference), Presidio's latency is dominated by spaCy NER which is CPU-bound. We wrap the analysis call in `asyncio.to_thread()` to avoid blocking the event loop, preserving pipeline concurrency for PET-6's `asyncio.gather` fan-out.

### anonymize() function

```python
def anonymize(
    text: str,
    findings: Sequence[ScanFinding],
    *,
    mode: Literal["redact", "replace", "hash", "mask"] = "redact",
    hash_key: str | None = None,
) -> str: ...
```

A standalone module-level function, **not** a method on `PresidioScanner`. The pipeline (PET-6) calls this after merging findings from all scanners. Key behaviors:

1. **Lazy-load `presidio_anonymizer`.** Imports `AnonymizerEngine` and operator types on first call and caches the engine instance in a module-level `_module_anonymizer: AnonymizerEngine | None` variable, guarded by a module-level `threading.Lock` to prevent TOCTOU races under concurrent calls. The `_HmacSha256Operator` is registered via `add_anonymizer()` during this setup (idempotent — safe if called again). Subsequent calls reuse the cached engine. This is separate from the `PresidioScanner` instance's `self._anonymizer` — the standalone function cannot access instance state. Raises `ImportError` if missing — this is a safety net, not a normal path (the pipeline verifies the extra is installed before calling).

2. **Finding filter and conversion.** First, filter to findings with `position is not None` — findings without position data (from PET-3/4) are silently skipped. Then recover the entity type from each finding's `rule_id` (see below). The filtered+typed findings are the input to the mode-specific anonymization path.

   **Entity type recovery:** `ScanFinding` does not carry an `entity_type` field; the entity type is encoded in `rule_id`. For Presidio-originated findings (`rule_id` starts with `"petasos.presidio."`), the entity type is recovered by stripping the `"petasos.presidio."` prefix, upper-casing, and replacing hyphens with underscores: e.g., `"petasos.presidio.person"` → `"PERSON"`, `"petasos.presidio.us-ssn"` → `"US_SSN"`. For findings from other scanners that happen to have position data, the raw `rule_id` suffix (after last `.`) is upper-cased and hyphen-replaced as a best-effort entity type — these are uncommon but the function handles them gracefully.

3. **Dual-path anonymization by mode.** Presidio's `AnonymizerEngine.anonymize()` takes `operators: Dict[str, OperatorConfig]` keyed by entity type — one config per entity type, applied uniformly to all findings of that type. This works for **redact** and **hash** modes (uniform behavior per entity type). It does **not** work for **replace** (per-finding counter labels) or **mask** (per-finding `chars_to_mask` based on matched text length). See "Decision: dual-path anonymization" below.

4. **HMAC-SHA256 for hash mode.** When `hash_key` is provided and `mode="hash"`, we use the custom `_HmacSha256Operator` (registered via `engine.add_anonymizer()`) with `OperatorConfig("hmac_sha256", {"hmac_key": hash_key})`. When `hash_key is None`, we use Presidio's built-in `Hash` operator with `hash_type="sha256"`.

   HMAC-SHA256 makes hashes correlatable across sessions (same PII + same key = same hash), which PET-9's premium audit trails require.

   **Note:** Presidio's built-in `Hash` operator (v2.2.361+) adds a random salt by default, making hashes non-deterministic across calls. Plain hash mode (`hash_key=None`) is therefore **not correlatable** — callers who need cross-call consistency must provide a `hash_key`.

5. **Return value.** Presidio's `AnonymizerEngine.anonymize()` returns an `EngineResult` object; the function extracts `.text` from it. For manual-path modes (replace, mask), the function returns the modified string directly. In both cases, `anonymize()` returns `str`.

### Decision: dual-path anonymization (engine vs manual)

Presidio's `AnonymizerEngine.anonymize()` applies a single `OperatorConfig` per entity type. Two modes have uniform per-entity-type behavior; two require per-finding variation:

| Mode | Path | Reason |
|---|---|---|
| `"redact"` | **Engine** — `Replace(new_value=f"<{entity_type}>")` | Same placeholder for all findings of a type |
| `"hash"` | **Engine** — `Hash(hash_type="sha256")` or `hmac_sha256` operator | Same operator; output varies because input text varies |
| `"replace"` | **Manual** — string slicing with position data | Each finding needs a distinct counter label (`<PERSON_1>`, `<PERSON_2>`) |
| `"mask"` | **Manual** — string slicing with position data | Each finding needs a different `chars_to_mask` based on its length |

**Engine path** (redact, hash): Convert filtered findings to Presidio `RecognizerResult` objects, sort by `start` position, build per-entity-type `OperatorConfig` dict, call `engine.anonymize(text, recognizer_results, operators)`, return `result.text`.

**Manual path** (replace, mask): Three steps:

1. **Overlap resolution.** Before applying replacements, deduplicate overlapping findings. Sort findings by `start` position. Walk forward: if finding B overlaps with finding A (B.start < A.end), keep the finding with higher `confidence` (longer span as tiebreaker). Drop the other. This produces a non-overlapping set.

2. **Matched-text recovery.** For each finding, resolve the matched text: use `finding.matched_text` if not `None`, otherwise fall back to `text[finding.position.start:finding.position.end]`. This handles findings from scanners that populate position but not `matched_text`.

3. **Reverse-order application.** Process the non-overlapping findings in **reverse position order** (highest `start` first) so that string slicing for earlier positions is not invalidated by later replacements. For each finding, compute the replacement string and splice it into the text using `text[:start] + replacement + text[end:]`.

Mode-specific behavior:

- **Replace:** Assign counter labels in forward position order first (increment-then-use: first `PERSON` gets `_1`, second gets `_2`), then apply replacements in reverse.
- **Mask:** Compute `chars_to_mask` per finding using the resolved matched text (see mask formula below), build the masked string (`"*" * chars_to_mask + resolved_text[chars_to_mask:]`), apply in reverse.

This dual-path approach avoids fighting Presidio's API while keeping redact and hash modes leveraging Presidio's battle-tested engine for overlap resolution and whitespace handling.

### Decision: custom HMAC operator, not Presidio's built-in Hash

Presidio's `Hash` operator supports `sha256` and `sha512` but not HMAC. We implement HMAC-SHA256 as a custom `Operator` subclass (`_HmacSha256Operator`) that Presidio's `AnonymizerEngine` can consume via `add_anonymizer()` registration. The operator implements all four required methods from Presidio's `Operator` ABC:

```python
class _HmacSha256Operator(Operator):
    def operator_name(self) -> str:
        return "hmac_sha256"

    def operator_type(self) -> OperatorType:
        return OperatorType.Anonymize

    def validate(self, params: dict[str, Any] | None = None) -> None:
        if not params or not isinstance(params.get("hmac_key"), str):
            raise ValueError("hmac_key (str) is required")

    def operate(self, text: str, params: dict[str, Any] | None = None) -> str:
        if not params or "hmac_key" not in params:
            raise ValueError("hmac_key is required")
        key = params["hmac_key"].encode("utf-8")
        return hmac.new(key, text.encode("utf-8"), hashlib.sha256).hexdigest()
```

All four methods match Presidio's `Operator` ABC signatures exactly (instance methods, `params` optional in both `validate` and `operate`). `mypy --strict` clean.

The operator is registered on the `AnonymizerEngine` instance via `engine.add_anonymizer(_HmacSha256Operator)` during the `anonymize()` function's lazy setup. This makes it available as operator name `"hmac_sha256"` in `OperatorConfig`.

### Decision: replace mode uses entity-scoped counters

In `"replace"` mode, synthetic values are `<PERSON_1>`, `<PERSON_2>`, `<EMAIL_ADDRESS_1>`, etc. — counters are scoped per entity type within a single `anonymize()` call. This ensures the same entity appearing twice gets distinct synthetic labels (useful for audit trails), while keeping the counter deterministic within a single call.

Implementation: a `defaultdict(int)` counter. For each finding in forward position order, increment the counter for its entity type first, then use the new value as the label index (increment-then-use). First `PERSON` → counter becomes 1 → `<PERSON_1>`. Second `PERSON` → counter becomes 2 → `<PERSON_2>`. The counter is local to each `anonymize()` call — no state leaks between calls.

### Decision: mask mode hides leading characters

Masking replaces leading characters with `*`, leaving trailing characters visible. The number of characters to mask is computed per finding:

```python
visible = 4  # hardcoded for v1
resolved_text = finding.matched_text or text[start:end]  # fallback if matched_text is None
length = len(resolved_text)
if length <= visible:
    chars_to_mask = length       # mask everything for short values
else:
    chars_to_mask = length - visible  # mask leading, show trailing
```

For short values (≤4 chars), the **entire value is masked** — no PII leaks. For longer values, the last 4 characters are visible: `555-1234` → `****1234`, `John Smith` → `******mith`. This matches common PII masking conventions.

Implementation uses the manual path (see "Decision: dual-path anonymization"): build the masked string as `"*" * chars_to_mask + resolved_text[chars_to_mask:]` and splice into the text at the finding's position. Processed in reverse position order after overlap resolution.

---

## Test plan

### Unit tests (no Presidio dependency required)

- **Severity mapping completeness:** verify every entity type in `_SEVERITY_MAP` maps to the expected `Severity` value. Verify unknown types default to `LOW`.
- **Finding conversion round-trip:** construct `ScanFinding` objects with known positions, convert to `RecognizerResult` via the internal helper, verify fields map correctly.
- **Counter-based replace labels:** verify `<PERSON_1>`, `<PERSON_2>` incrementing within a call, and that counters reset across calls.

### Integration tests (require `presidio-analyzer` + `presidio-anonymizer` + spaCy model)

- **Detection corpus (20 messages).** A fixture of 20 messages containing known PII:
  - Credit card numbers (CRITICAL severity)
  - Social security numbers (CRITICAL)
  - Email addresses (HIGH)
  - Phone numbers (HIGH)
  - Person names (MEDIUM)
  - Locations (MEDIUM)
  - IP addresses (HIGH)
  - Messages with no PII (clean pass-through)
  - Messages with multiple PII types (multi-finding)
  - Messages with overlapping/adjacent PII spans

- **Position accuracy:** for each detected finding, verify `position.start` and `position.end` correspond to the actual PII substring in the input.

- **Confidence scores:** verify all findings have `confidence > 0.0` and `confidence <= 1.0`.

- **Scanner protocol compliance:** verify `isinstance(PresidioScanner(), Scanner)` is `True`.

- **name property:** verify `PresidioScanner().name == "presidio"`.

- **Anonymization modes:**
  - `redact`: input with known PII → output has `<ENTITY_TYPE>` placeholders
  - `replace`: output has `<ENTITY_TYPE_N>` counter-based placeholders
  - `hash` without key: output has SHA256 hex digests
  - `hash` with key: output has HMAC-SHA256 hex digests; same input+key → same hash (deterministic)
  - `hash` correlation: two different PII values with same key produce different hashes; same PII with same key across two calls produces the same hash
  - `mask`: output has leading characters replaced with `*`, trailing visible

- **Unsorted findings:** pass findings in reverse position order to `anonymize()` → verify correct output (internal sort handles it).

- **Overlapping findings (engine path):** two findings with overlapping spans in redact/hash mode → verify Presidio's engine resolves overlaps without corruption.

- **Overlapping findings (manual path):** two findings with overlapping spans in replace/mask mode → verify overlap resolution deduplicates (keeps higher confidence / longer span), output is not corrupted.

- **`matched_text=None` findings:** pass `ScanFinding` with `position` set but `matched_text=None` to `anonymize()` in mask mode → verify fallback to `text[start:end]` produces correct masked output.

- **All-unpositioned findings:** `anonymize(text, findings)` where every finding has `position=None` → returns original text unchanged.

- **Empty findings list:** `anonymize(text, [])` → returns original text unchanged.

- **Empty text:** `scan("")` → returns `ScanResult` with empty findings. `anonymize("", [])` → returns `""`.

- **Findings without position:** pass `ScanFinding` objects with `position=None` (as PET-3/4 would produce) → silently skipped, positioned findings still anonymized.

- **Score threshold filtering:** construct scanner with `score_threshold=0.9` → verify low-confidence findings (below 0.9) are excluded from results.

### Error-path tests

- **Lazy-load failure (import):** mock `presidio_analyzer` as unavailable → `scan()` returns errored `ScanResult` with install instructions, no exception raised.
- **spaCy model missing:** mock `AnalyzerEngine()` constructor to raise → errored `ScanResult` with model download instructions.
- **Backend exception during analyze:** mock `analyzer.analyze()` to raise → errored `ScanResult`, no exception propagated.
- **Fail-open under exception:** verify that backend errors produce `ScanResult(error=..., findings=())`, not exceptions.
- **anonymize() import failure:** call `anonymize()` without `presidio_anonymizer` installed → `ImportError` raised (this is the expected safety-net behavior).

### Lint and type-check

- `mypy --strict` clean on `petasos/scanners/presidio.py`
- `ruff check` and `ruff format` clean

---

## Test command

```bash
C:\Users\zioni\AppData\Local\Programs\Python\Python311\python.exe -m pytest tests/test_presidio_scanner.py -v
```

For full suite including lint and type-check:

```bash
C:\Users\zioni\AppData\Local\Programs\Python\Python311\python.exe -m pytest tests/test_presidio_scanner.py -v && ruff check petasos/scanners/presidio.py && ruff format --check petasos/scanners/presidio.py && mypy --strict petasos/scanners/presidio.py
```

---

## Done when

- [ ] `PresidioScanner` class in `petasos/scanners/presidio.py` implements the `Scanner` protocol
- [ ] Lazy-load pattern: `import presidio_analyzer` / `presidio_anonymizer` fails → returns errored `ScanResult`, no crash
- [ ] spaCy model missing → clear error message in `ScanResult.error`, no crash
- [ ] Constructor params: `entities`, `language`, `score_threshold` — all functional
- [ ] `RecognizerResult` → `ScanFinding` mapping: entity type, position, confidence, matched_text all populated
- [ ] Severity mapping by entity type category (CRITICAL/HIGH/MEDIUM/LOW) as specified
- [ ] `name` property returns `"presidio"`
- [ ] Duration tracking via `time.perf_counter`
- [ ] `scan()` wraps synchronous Presidio call in `asyncio.to_thread()`
- [ ] `anonymize(text, findings, mode, hash_key=None)` function exported from module
- [ ] Anonymization correct for all four modes: redact, replace, hash, mask
- [ ] HMAC-SHA256 hash mode produces deterministic, correlatable hashes (same input + key = same hash)
- [ ] Plain SHA256 fallback when no key provided
- [ ] Replace mode uses entity-scoped counters (`<PERSON_1>`, `<PERSON_2>`)
- [ ] Mask mode hides leading characters, shows trailing
- [ ] Manual-path overlap resolution: overlapping findings deduplicated before replacement (higher confidence wins, longer span tiebreaker)
- [ ] Manual-path `matched_text=None` fallback: uses `text[start:end]` when `matched_text` is not populated
- [ ] Anonymizer handles unsorted findings correctly (internal sort)
- [ ] Findings without position silently skipped in anonymization
- [ ] `_ensure_loaded()` guarded by threading.Lock for concurrent `asyncio.to_thread()` safety
- [ ] Integration tests against real `presidio-analyzer` with 20-message corpus containing known PII
- [ ] `pip install petasos[presidio]` succeeds in clean Python 3.11 venv
- [ ] Fail-open verified under backend exception (not just import failure)
- [ ] ≥20 tests passing (detection + anonymization + error paths)
- [ ] `mypy --strict` clean
- [ ] `ruff check` / `ruff format` clean

---

## Deferred (P2+)

- **Concurrent `scan()` on same instance** (P4): `_ensure_loaded()` may run twice under concurrent calls. Low risk — engine creation is idempotent, and the lock added in v4 resolves the TOCTOU race.
- **`score_threshold` semantics** (P3): Presidio's threshold is `>=` (inclusive). PET-5 passes the value through; no custom semantics.
- **`anonymize()` docstring** (P4): Public API export warrants a one-line docstring. Left to implementer discretion per CLAUDE.md "default to writing no comments" with the public-API exception.

---

## Out of scope

- **Multi-language PII detection** — English only. Additional spaCy models are a future enhancement.
- **Custom recognizers** — Presidio supports user-defined recognizers (regex, deny-lists, ML); we expose only the built-in set. Custom recognizer registration is future work.
- **LLM-based recognizers** — Presidio v2.2.362 added LangExtract-based PII detection (LLM/SLM). We use the traditional NLP pipeline. LLM recognizers are a future premium feature candidate.
- **Image PII detection** — Presidio has an image redactor module. Text-only for PET-5.
- **Deanonymization / reversible anonymization** — the `anonymize()` function is one-way. Presidio's `Deanonymize` operator is not exposed.
- **Pipeline integration** — PET-6 consumes this scanner and calls `anonymize()`. Wiring is PET-6 scope.
- **Frequency, escalation, profiles** — premium tier (PET-7+).
- **Auto-download of spaCy models** — user must install manually. A future CLI `petasos setup` may address this.
- **Configurable mask visible-char count** — hardcoded to 4 for v1. Expose as parameter if PET-6 needs it.
- **Profile-driven severity overrides** — the severity map is static. Profile-based adjustment is PET-8 scope.
