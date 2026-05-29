# PET-6 — Pipeline Orchestration (OSS Tier Complete)

## Goal

Ship the `Pipeline` class and `PetasosConfig` dataclass — the central orchestrator that wires normalization, syntactic pre-filtering, concurrent scanner fan-out, finding merge, fail-mode enforcement, and PII anonymization into a single `await pipeline.inspect()` call. When this lands, the OSS tier is shippable: `pip install petasos[all]` gives real security coverage with zero premium dependencies.

## Scope

### New files

| File | Purpose |
|------|---------|
| `petasos/config.py` | `PetasosConfig` dataclass — all pipeline settings, JSON-serializable, validated on construction |
| `petasos/pipeline.py` | `Pipeline` class — central orchestrator with 7-stage `inspect()` method |
| `tests/test_pipeline.py` | Pipeline orchestration tests (>=40) |
| `tests/test_config.py` | Config validation + serialization tests (>=10) |
| `tests/test_finding_merge.py` | Finding deduplication + severity aggregation tests (>=10) |

### Modified files

| File | Change |
|------|--------|
| `petasos/__init__.py` | Export `Pipeline`, `PetasosConfig` |
| `petasos/_types.py` | No changes expected — `PipelineResult` already defined with the right shape |

### Files left alone

- `petasos/normalize.py` — consumed as-is
- `petasos/scanners/*.py` — consumed as-is; no scanner changes
- All existing test files — no modifications

## Decisions

### D1 — `asyncio.gather` with per-scanner exception wrapping, not `asyncio.TaskGroup`

`TaskGroup` cancels siblings on first failure. For a security pipeline, all scanners must finish independently — a slow LLM Guard scan must not cancel a fast Presidio scan. `gather(return_exceptions=True)` plus manual result inspection gives the right semantics.

Implementation: wrap each scanner call in an async helper that catches `Exception` (not `BaseException` — `KeyboardInterrupt` and `SystemExit` must propagate) and returns an errored `ScanResult`. Pass all helpers to `asyncio.gather`.

### D2 — MinimalScanner runs first, synchronously, before fan-out

MinimalScanner is < 5ms and zero-dep. Running it before fan-out means the syntactic baseline is always available even if `asyncio.gather` hits an edge case. It also provides early-exit data: in `closed` mode, a critical syntactic finding short-circuits before ML scanner fan-out.

Implementation: `Pipeline.inspect()` calls `MinimalScanner.scan()` directly (awaited), appends its result, then fans out remaining scanners.

### D3 — Fail-mode defaults to `degraded`, not `open`

Security library — silent failure is worse than brief conservatism.

### D4 — Premium hooks are no-op methods on Pipeline, not a plugin/middleware chain

Three known premium stages with fixed execution order. A middleware chain adds abstraction without value. Direct method calls are testable, type-safe, and debuggable.

### D5 — `PetasosConfig` is a standalone dataclass, not subclassed from Drawbridge config

Petasos is uncoupled from Drawbridge. Own config shape, own serialization, own validation.

### D6 — Pipeline constructor takes a defensive copy of config

Per Hermes Desktop footgun §3 (snapshot-on-start): mutating the config object after pipeline construction must not change pipeline behavior. `copy.deepcopy` on construction.

### D7 — Scanners are a Pipeline constructor argument, not a PetasosConfig field

The brief lists `scanners: list[Scanner]` as a PetasosConfig field, but Scanner protocol instances are not JSON-serializable. Since the brief also requires "Every field JSON-serializable," these requirements conflict. Resolution: `PetasosConfig` holds pure configuration data (all JSON-serializable). Scanner instances are passed to `Pipeline.__init__()` separately. This keeps config serialization clean and separates runtime objects from declarative settings.

### D8 — PetasosConfig uses top-level `petasos:` key for Hermes config serialization

Per Hermes Desktop footgun §2: the UI model switcher wipes anything under `model:`. Petasos config must be a top-level YAML key. `PetasosConfig.to_dict()` / `from_dict()` methods support this.

## Design

### 4.1 PetasosConfig (`petasos/config.py`)

```python
@dataclass(frozen=True)
class PetasosConfig:
    # Normalization toggles
    normalize_nfkc: bool = True
    strip_zero_width: bool = True
    map_homoglyphs: bool = True
    detect_rtl_override: bool = True

    # Scanning
    direction: Direction = "inbound"
    fail_mode: Literal["open", "closed", "degraded"] = "degraded"

    # Anonymization
    anonymize: bool = False
    pii_entities: tuple[str, ...] = ()
    redaction_mode: Literal["redact", "replace", "hash", "mask"] = "redact"
    hash_key: str | None = None

    # Premium stubs (accepted but no runtime effect until PET-7+)
    frequency_enabled: bool = False
    escalation_enabled: bool = False
    profile_name: str | None = None
    tool_guard_enabled: bool = False
    audit_enabled: bool = False
    alert_enabled: bool = False
```

**Frozen dataclass** — immutable after construction. Pipeline takes a defensive `copy.deepcopy` anyway (D6), but frozen enforces the intent at the type level for mutable nested structures (e.g., if `pii_entities` were a list — it's a tuple specifically to avoid that).

**Validation on `__post_init__`:**
- `direction` must be `"inbound"` or `"outbound"`
- `fail_mode` must be one of the three literals (enforced by type, but runtime-checked for dict/JSON construction paths)
- `redaction_mode` must be one of four literals
- `hash_key` required when `redaction_mode == "hash"` and `anonymize == True`
- `pii_entities` entries must be non-empty strings

**Serialization:**
- `to_dict() -> dict[str, Any]` — all fields, JSON-safe values
- `from_dict(data: dict[str, Any]) -> PetasosConfig` — classmethod, validates on construction
- Round-trip: `PetasosConfig.from_dict(config.to_dict()) == config`

### 4.2 Pipeline (`petasos/pipeline.py`)

```python
class Pipeline:
    def __init__(
        self,
        scanners: Sequence[Scanner] = (),
        *,
        config: PetasosConfig | None = None,
    ) -> None: ...

    async def inspect(
        self,
        text: str,
        *,
        direction: Direction | None = None,
        session_id: str | None = None,
    ) -> PipelineResult: ...
```

**Constructor:**
- Stores `copy.deepcopy(config)` (D6). If `config is None`, uses `PetasosConfig()` (all defaults).
- Stores scanner list as a tuple (immutable snapshot).
- Separates scanners into `_minimal_scanner` (the first MinimalScanner found, or a fresh one if none provided) and `_ml_scanners` (everything else).
- Sets `_premium_active = False` (stub for PET-10 license gate).

**`inspect()` stages:**

1. **Normalize** — call `petasos.normalize.normalize(text)`, which returns a `NormalizedText` object (`.normalized` for the transformed string, `.rtl_overrides_detected` for RTL detection). If normalization toggles are partially disabled in config, apply only the enabled steps. The current `normalize()` function applies all steps unconditionally — PET-6 calls it as-is (all toggles default to True). A future ticket can add per-step control to `normalize()` itself. For now, if any normalization toggle is False, skip normalization entirely and use raw text. This is conservative: partial normalization could mask attack vectors.

2. **Syntactic pre-filter** — `await self._minimal_scanner.scan(text, direction=direction, session_id=session_id)`. Always runs. Receives the **original raw text**, not the normalized text — MinimalScanner calls `normalize()` internally in `_scan_impl()` and handles its own structural checks on raw input before normalizing. Passing pre-normalized text would cause double normalization. Result stored.

3. **Early exit (closed mode)** — if `fail_mode == "closed"` and MinimalScanner produced any CRITICAL findings, skip ML fan-out. Return `PipelineResult(safe=False, findings=minimal_result.findings, scanner_results=(minimal_result,), sanitized_content=None, errors=())`. Rationale (D2): saves ML scanner latency when the syntactic baseline already blocks.

4. **Fan-out scan** — for each scanner in `_ml_scanners`, pass **normalized text** (ML scanners do not normalize internally, unlike MinimalScanner):
   ```python
   async def _scan_one(scanner: Scanner, ...) -> ScanResult:
       sname = getattr(scanner, "name", "unknown")
       t0 = time.perf_counter()
       try:
           return await asyncio.wait_for(
               scanner.scan(normalized_text, direction=direction, session_id=session_id),
               timeout=30.0,
           )
       except Exception as exc:
           elapsed = (time.perf_counter() - t0) * 1000
           return ScanResult(scanner_name=sname, findings=(), duration_ms=elapsed, error=str(exc))
   ```
   Captures `scanner.name` into a local before the try block (if `.name` itself raises, `"unknown"` is used). Records `duration_ms` even in error paths, consistent with existing scanner implementations. Catches `Exception`, not `BaseException` — `KeyboardInterrupt` and `SystemExit` must propagate. All scanners run via `asyncio.gather(*tasks)` (D1). 30-second per-scanner timeout prevents a hung scanner from blocking the pipeline. Scanners are responsible for their own thread safety (e.g., PresidioScanner uses `asyncio.to_thread` internally).

5. **Merge findings** — collect all findings from all scanner results (MinimalScanner + ML scanners). Deduplicate overlapping positioned findings (§4.3). Compute aggregate severity (highest severity across all retained findings, used internally for fail-mode).

6. **Premium frequency hook** — `await self._premium_frequency_hook(findings, session_id)`. No-op in PET-6. Positioned here per the CLAUDE.md architecture diagram: after merge, before fail-mode.

7. **Premium escalation hook** — `await self._premium_escalation_hook(findings, session_id)`. No-op in PET-6. After frequency, before fail-mode.

8. **Fail-mode enforcement** — evaluate scanner health (§4.4). Set `safe` flag.

9. **Anonymize** — if `config.anonymize` is True and PII findings exist (any finding with `finding_type == "pii"`), call `petasos.scanners.presidio.anonymize()` with the configured mode and hash_key. The call is wrapped in `try/except (ImportError, Exception)`: on `ImportError`, append `"presidio not installed: anonymization skipped"` to errors; on other exceptions, append the error string. In either case, `sanitized_content` is `None`. If Presidio is available and succeeds, store the result as `sanitized_content`.

10. **Premium audit hook** — `await self._premium_audit_hook(result, session_id)`. No-op in PET-6. After anonymization.

11. **Premium alert hook** — `await self._premium_alert_hook(result, session_id)`. No-op in PET-6. After audit.

12. **Return `PipelineResult`** — assemble `safe`, `findings`, `sanitized_content`, `scanner_results`, `errors`.

**Pipeline never throws** — the entire `inspect()` body is wrapped in a top-level try/except that catches `Exception` and returns a `PipelineResult(safe=False, findings=(), errors=(str(exc),))`. `BaseException` subclasses (`KeyboardInterrupt`, `SystemExit`) are **not** caught — they must propagate to allow clean process shutdown.

### 4.3 Finding Merge (standalone function in `pipeline.py`)

```python
def merge_findings(
    results: Sequence[ScanResult],
) -> tuple[ScanFinding, ...]:
```

Algorithm:
1. Collect all findings from all results.
2. Separate into positioned (have `position != None`) and unpositioned.
3. Sort positioned findings by `position.start`.
4. Sweep with a running "current winner": initialize `current` to the first positioned finding. For each subsequent finding `next`:
   - If `next.position.start < current.position.end` (overlap): compare `next` against `current`. Keep the one with higher confidence. On confidence tie, keep higher severity. On double tie, emit `current` to output and set `current = next` — both findings appear in the final result (different scanners may provide complementary info).
   - If no overlap: emit `current` to the output, set `current = next`.
   - After the loop, emit the final `current`.
   This handles transitive overlaps correctly (e.g., findings at [0,10], [5,15], [8,20] — the third is compared against the winner of the first two, not just the second).
5. Concatenate surviving positioned findings + all unpositioned findings.
6. Return as tuple.

**Severity ordering:** `Severity` is a string-valued enum (`"critical"`, `"high"`, etc.) with no natural ordering in Python. Define an explicit rank dict:
```python
_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2,
    Severity.LOW: 3, Severity.INFO: 4,
}
```
Lower rank = higher severity. Use `_SEVERITY_RANK[f.severity]` for comparisons.

### 4.4 Fail-Mode Enforcement

Input: list of `ScanResult` objects (one per scanner).

Classify scanners:
- **Syntactic** — `scanner_name == "minimal"` (MinimalScanner). Never counts as failed for fail-mode.
- **ML** — everything else.

Determine ML health:
- `ml_scanners_total` = count of ML scanners
- `ml_scanners_errored` = count of ML scanners with `error is not None`
- `partial_failure` = `0 < ml_scanners_errored < ml_scanners_total`
- `all_ml_failure` = `ml_scanners_errored == ml_scanners_total` (and `ml_scanners_total > 0`)

Determine `safe`:
- Start with `safe = True` (no findings = safe).
- If any finding has severity CRITICAL or HIGH: `safe = False`.
- Apply fail-mode override:

| Mode | Partial ML failure | All ML failure |
|------|-------------------|----------------|
| `degraded` | `safe` unchanged (reduced coverage accepted) | `safe = False` |
| `open` | `safe` unchanged | `safe` unchanged |
| `closed` | `safe = False` | `safe = False` |

- If `ml_scanners_total == 0` (no ML scanners configured): fail-mode does not apply. `safe` is determined solely by findings.

### 4.5 Anonymization Integration

Anonymization runs only when ALL of:
1. `config.anonymize is True`
2. There are PII findings (`finding_type == "pii"`) in the merged findings
3. Presidio is importable

If Presidio is not installed, record an error string in the result but do not set `safe = False` for this reason alone — the scan findings are still valid, anonymization is a post-processing step.

Call `petasos.scanners.presidio.anonymize(text, pii_findings, mode=config.redaction_mode, hash_key=config.hash_key)`.

**Which text to pass to anonymize:** The text must match the text that generated the PII findings. Since PresidioScanner is an ML scanner and receives **normalized text** (stage 4), its position offsets refer to the normalized text. Therefore, `anonymize()` must also receive the normalized text. If positions from MinimalScanner findings (which refer to raw or internally-normalized text) are mixed in, only PII findings (from PresidioScanner) are passed to anonymize — MinimalScanner does not produce `finding_type == "pii"` findings, so this is self-selecting.

### 4.6 Premium Hooks

Four async no-op methods on `Pipeline`:

```python
async def _premium_frequency_hook(
    self, findings: tuple[ScanFinding, ...], session_id: str | None
) -> None:
    pass

async def _premium_escalation_hook(
    self, findings: tuple[ScanFinding, ...], session_id: str | None
) -> None:
    pass

async def _premium_audit_hook(
    self, result: PipelineResult, session_id: str | None
) -> None:
    pass

async def _premium_alert_hook(
    self, result: PipelineResult, session_id: str | None
) -> None:
    pass
```

Each hook checks `self._premium_active` before doing work (currently always False). PET-7/8/9 replace the bodies with real implementations. Signatures are fixed for PET-6 — if PET-7 needs additional context, the hook signature will be updated in that ticket.

Note: the brief's Technical Risks table recommends `**kwargs` for forward compatibility. This spec rejects that in favor of concrete typed signatures that pass `mypy --strict`. Signature changes in PET-7+ are expected and acceptable — the cost of updating call sites is lower than the cost of untyped hook parameters.

## Test plan

### test_config.py (>=10 tests)

- Default construction produces valid config with expected defaults
- `from_dict()` / `to_dict()` round-trip preserves all fields
- Validation rejects invalid `direction` value
- Validation rejects invalid `fail_mode` value
- Validation rejects invalid `redaction_mode` value
- Validation requires `hash_key` when `redaction_mode="hash"` and `anonymize=True`
- Frozen dataclass prevents mutation
- `from_dict()` with partial data fills defaults
- `from_dict()` with extra keys ignores them (forward compatibility)
- Empty `pii_entities` tuple is valid
- Premium stub fields default to disabled

### test_finding_merge.py (>=10 tests)

- No findings → empty tuple
- Non-overlapping findings preserved in order
- Overlapping findings: higher confidence wins
- Overlapping findings: equal confidence → higher severity wins
- Overlapping findings: double tie → both kept
- Unpositioned findings always kept
- Findings from different scanners with same position range deduplicated
- Single finding passes through unchanged
- Many non-overlapping findings from multiple scanners preserved
- Mixed positioned and unpositioned findings handled correctly

### test_pipeline.py (>=40 tests)

**Construction (5):**
- Pipeline with no scanners uses MinimalScanner only
- Pipeline with explicit MinimalScanner doesn't duplicate it
- Pipeline with ML scanners separates them from MinimalScanner
- Pipeline with None config uses defaults
- Pipeline defensive-copies config (mutation after construction is inert)

**Normalization stage (3):**
- Input is normalized before scanning (homoglyph in input, finding on normalized text)
- Normalization toggles: all disabled → raw text used
- Empty string input → valid PipelineResult with safe=True

**Syntactic pre-filter (3):**
- MinimalScanner always runs (even with no ML scanners)
- MinimalScanner findings included in result
- MinimalScanner error → error recorded, pipeline continues

**Fan-out scan (6):**
- Single ML scanner runs and findings included
- Multiple ML scanners run concurrently (timing assertion: total time < sum of individual times)
- Scanner exception → errored ScanResult, other scanners unaffected
- Scanner timeout → errored ScanResult after 30s
- Scanner returning empty findings → valid result
- All scanners returning empty → safe=True

**Finding merge (3):**
- Findings from MinimalScanner + ML scanner merged
- Overlapping findings deduplicated across scanners
- Aggregate severity is highest across all retained findings

**Fail-mode: degraded (5):**
- No ML failures → safe determined by findings only
- Partial ML failure → safe unchanged (reduced coverage accepted)
- All ML failure → safe=False regardless of findings
- No ML scanners configured → fail-mode not applied
- CRITICAL finding from MinimalScanner → safe=False

**Fail-mode: open (3):**
- Partial ML failure → safe unchanged
- All ML failure → safe unchanged
- Findings still determine safe flag normally

**Fail-mode: closed (4):**
- Partial ML failure → safe=False
- All ML failure → safe=False
- Early exit on CRITICAL MinimalScanner finding (ML scanners not called)
- No findings + no errors → safe=True

**Anonymization (5):**
- PII findings + anonymize=True → sanitized_content populated
- No PII findings → sanitized_content is None
- anonymize=False → sanitized_content is None regardless of PII
- Presidio not installed → error recorded, sanitized_content is None
- Hash mode with hash_key produces deterministic output

**Pipeline never throws (4):**
- Completely broken scanner → PipelineResult returned, not exception
- Invalid input type → PipelineResult with error
- Internal pipeline error → PipelineResult with error
- `KeyboardInterrupt` propagates (not caught by pipeline's Exception handler)

**Premium hooks (2):**
- Hooks callable without error
- Hooks are no-ops (pipeline result unchanged)

**Direction parameter (2):**
- Direction from inspect() overrides config default
- Direction=None uses config default

## Test command

```
python -m pytest tests/test_pipeline.py tests/test_config.py tests/test_finding_merge.py -v && python -m mypy --strict petasos/pipeline.py petasos/config.py && python -m ruff check petasos/pipeline.py petasos/config.py
```

## Done when

- [ ] Pipeline runs end-to-end with 0, 1, 2, or 3 scanners configured
- [ ] Concurrent scanner execution verified (timing assertions in tests)
- [ ] Finding deduplication works for overlapping position ranges across scanners
- [ ] Fail-mode `degraded`: partial ML failure → pass; all ML failure → block; syntactic always runs
- [ ] Fail-mode `open`: any failure → pass
- [ ] Fail-mode `closed`: any failure → block; early exit on CRITICAL syntactic finding
- [ ] Anonymization produces correct output for all four operator modes
- [ ] HMAC-SHA256 hash mode produces deterministic, correlatable hashes
- [ ] Pipeline never throws — all error paths return valid `PipelineResult`
- [ ] `PetasosConfig` serializes to/from dict correctly, validates on construction
- [ ] Pipeline constructor snapshots config (defensive copy)
- [ ] Premium hooks are present as no-ops, callable without error
- [ ] `mypy --strict` and `ruff` clean on new files
- [ ] >=60 tests across pipeline + config + finding merge

## Out of scope

- Frequency tracking / escalation tiers — PET-7
- Profile system / ToolCallGuard — PET-8
- Audit trails / alert rules — PET-9
- JWT license validation — PET-10
- Hermes integration testing — PET-11
- PyPI publish / v0.1.0-alpha.1 tag — PET-12
- Pipeline config hot-reload — explicitly out per snapshot-on-start
- Custom middleware / plugin hooks — D4 rejects this
- Per-step normalization toggle control on `normalize()` function — would require modifying `normalize.py`; PET-6 calls it as-is
- Latency benchmarks / budgets — deferred to PET-11 integration tests where real scanners are available

## Deferred (P2+)

Advisory items from Round 1 review — acknowledged, not blocking:

- **pii_entities not wired to anonymization filtering** (correctness P2 F-5): Config has `pii_entities` but `anonymize()` doesn't use it for entity-type filtering. The existing `anonymize()` signature doesn't accept entity filtering. Future enhancement when entity-selective anonymization is needed.
- **Aggregate severity computed but not stored** (correctness P2 F-11): `merge_findings` description mentions computing aggregate severity but `PipelineResult` has no field for it. The aggregate is used internally for fail-mode enforcement but not exposed. If needed, add `aggregate_severity` to `PipelineResult` in a future ticket.
- **All-or-nothing normalization toggle** (correctness P2 F-8): Disabling one toggle disables all normalization. Per-step control requires modifying `normalize.py` — tracked in Out of Scope.
- **Unicode position assumption** (edge-cases P2 F-6): All position values assumed to be Python `str` offsets (code points). Scanners wrapping C/Rust libraries that count bytes or UTF-16 code units must convert before returning `Position`. This is a scanner-level contract, not a pipeline concern.
- **`asyncio.wait_for` cancellation** (edge-cases P2 F-9): `wait_for` cancels the scanner's task on timeout. Scanners with cleanup in `finally` blocks should handle `asyncio.CancelledError` if needed.
- **Wiki update needed post-PET-6** (conventions P2 F-1): Wiki filemap should be updated to reflect `pipeline.py` and `config.py` after merge.
- **Early exit is a spec-level decision** (conventions P2 F-2): The brief mentions early-exit as a possibility; this spec makes it concrete for `closed` mode + CRITICAL findings. This is a reasonable optimization, not a scope expansion.
- **MinimalScanner detection mechanism** (edge-cases R2 P2 F-3): Detection uses `scanner.name == "minimal"`. If no scanner with that name is provided, a fresh `MinimalScanner()` is created. If multiple share the name, the first is used as syntactic; the rest are ML. Implementation detail — not spec-blocking.
- **Empty text early return** (edge-cases R2 P2 F-1): `pipeline.inspect("")` could short-circuit before ML fan-out to avoid invoking ML models with empty input. Implementation optimization — test plan covers correctness.
- **MinimalScanner error in fail-mode** (edge-cases R2 P2 F-8): If MinimalScanner errors, the syntactic baseline is lost. In `closed`/`degraded` modes, this should be treated as a significant event. Implementation should append the error to the pipeline's error list and consider setting `safe=False` in `closed` mode.
