# PET-9: Audit Trails + Alert Rules — Spec

**Ticket:** PET-9 (`eead598f-13ac-44e1-8cd8-4794f550b833`)
**Phase:** 6
**Brief:** `docs/briefs/PET-9-audit-alerting.md`

---

## Goal

Ship two premium modules — `AuditEmitter` and `AlertManager` — that fill the existing pipeline stub hooks (`_premium_audit_hook`, `_premium_alert_hook`) with operational observability. AuditEmitter produces tamper-evident event records at configurable verbosity levels. AlertManager evaluates five built-in security rules against scan results and frequency state, with dual rate limiting and critical-alert exemption. Both modules are callback-driven, zero-network, and gated behind the premium activation + per-feature config toggles.

---

## Scope

### Files to create

| File | Purpose |
|------|---------|
| `petasos/premium/audit.py` | `AuditEmitter` class + `AuditEvent` dataclass |
| `petasos/premium/alerting.py` | `AlertManager` class + `Alert` dataclass + 5 built-in rules |
| `tests/test_audit.py` | Unit tests for AuditEmitter (≥25 tests) |
| `tests/test_alerting.py` | Unit tests for AlertManager (≥25 tests) |

### Files to modify

| File | Change |
|------|--------|
| `petasos/_types.py` | Export `AuditEvent` and `Alert` types |
| `petasos/premium/__init__.py` | Re-export `AuditEmitter`, `AlertManager`, `AuditEvent`, `Alert` |
| `petasos/pipeline.py` | Replace `_premium_audit_hook` / `_premium_alert_hook` stubs with real implementations; add `"audit"` and `"alerting"` to `_FEATURE_GATES`; update `_build_premium_features()` |
| `petasos/config.py` | Add alert rule threshold config fields + `audit_verbosity` (the boolean `audit_enabled` already exists) |
| `petasos/__init__.py` | Re-export `AuditEvent`, `Alert`, `AuditEmitter`, `AlertManager` in `__all__` |

### Files to leave alone

- All scanner files (`scanners/*.py`)
- `normalize.py`
- `premium/frequency.py`, `premium/escalation.py`, `premium/profiles.py`, `premium/guard.py`
- Test files for other modules

---

## Design

### 1. AuditEvent type (`petasos/_types.py`)

```python
@dataclass(frozen=True)
class AuditEvent:
    event_id: str                        # uuid4 hex string
    timestamp: float                     # time.time() — human-readable wall clock
    session_id: str | None
    event_type: str                      # "scan_complete" | "escalation" | "tier_change"
    payload: MappingProxyType[str, Any]  # depth controlled by verbosity; immutable
    sequence_number: int                 # monotonic per session, 0-indexed
```

Placed in `_types.py` alongside `PipelineResult` and `ScanFinding` to follow the existing convention of keeping protocol-visible types in the central types module. Frozen dataclass matches the project invariant. `payload` uses `MappingProxyType` (matching `PipelineResult.premium_features`) to enforce true immutability — prevents callback consumers from mutating shared event data.

### 2. Alert type (`petasos/_types.py`)

```python
@dataclass(frozen=True)
class Alert:
    alert_id: str                        # uuid4 hex string
    timestamp: float                     # time.time()
    rule_id: str                         # one of the 5 built-in IDs
    severity: str                        # "warning" | "high" | "critical"
    session_id: str | None
    message: str
    context: MappingProxyType[str, Any]  # rule-specific payload; immutable
```

Also frozen, also in `_types.py`. `context` uses `MappingProxyType` for the same immutability reason as `AuditEvent.payload`. The `severity` field is a plain string (not the `Severity` enum) because alert severity follows a different taxonomy than finding severity — alerts have "warning"/"high"/"critical" while findings have the 5-level `Severity` enum. Mixing them would create false type safety.

### 3. AuditEmitter (`petasos/premium/audit.py`)

**Constructor:**

```python
class AuditEmitter:
    def __init__(
        self,
        config: PetasosConfig,
        *,
        on_audit: Callable[[AuditEvent], None] | None = None,
    ) -> None:
```

Takes `config: PetasosConfig` following the established premium module pattern (`FrequencyTracker`, `AlertManager`). Reads `config.audit_verbosity` internally — no separate verbosity parameter.

- `_sequence_counters: dict[str, int]` — tracks per-session sequence numbers. Key is session_id; value is the next sequence number to assign. Sessions with `session_id=None` use the key `"__none__"`.
- `_last_emit_time: dict[str, float]` — tracks last emit time per session key (using `time.monotonic()`), for TTL-based pruning.
- No external deps. Uses only `uuid`, `time`, `dataclasses` from stdlib.

**`emit(result, session_id, freq_result)` method:**

Constructs an `AuditEvent` and invokes the callback. Returns the constructed event.

```python
def emit(
    self,
    result: PipelineResult,
    session_id: str | None,
    freq_result: FrequencyUpdateResult | None,
) -> AuditEvent:
```

Parameters:
- `result: PipelineResult` — the completed scan result
- `session_id: str | None` — the session identifier
- `freq_result: FrequencyUpdateResult | None` — frequency state (for standard/verbose payloads)

**Payload depth by verbosity:**

| Level | Payload contents |
|-------|-----------------|
| `minimal` | `safe`, `finding_count` |
| `standard` | minimal + `findings` (list of `{rule_id, severity, confidence}`), `escalation_tier`, `session_score` |
| `verbose` | standard + `scanner_results` (list of `{scanner_name, finding_count, duration_ms, error}`), `config_snapshot` (serialized `PetasosConfig.to_dict()`), `timing` dict |

**Sequence number contract:**

`sequence_number` is monotonically increasing per session_id (or per the `"__none__"` key for null sessions). The emitter guarantees no gaps at emission time. Gap detection is the consumer's responsibility. Implementation: `dict[str, int]` keyed on session_id, initialized to 0 on first emit, incremented post-emit.

**Callback error contract:**

The `on_audit` callback is invoked inside a `try/except Exception`. If the callback raises, the exception is caught and re-raised as a `RuntimeError` with the original exception chained (`raise RuntimeError(...) from exc`). The pipeline's existing try/except around `_premium_audit_hook` (pipeline.py:414-417) catches this and appends it to `result.errors`. The pipeline continues — audit is never fatal.

### Decision: Callback raises wrapped, not swallowed silently

The brief says "never throws" and "callback exceptions are caught and surfaced as a warning-level `PipelineResult.errors` entry." The AuditEmitter itself re-raises (wrapped) so the pipeline's existing try/except does the surfacing. This keeps the error-handling responsibility in one place (the pipeline) rather than duplicating it inside the emitter. The emitter is testable in isolation: a bad callback raises, and the pipeline integration test verifies it lands in `errors`.

### 4. AlertManager (`petasos/premium/alerting.py`)

**Constructor:**

```python
class AlertManager:
    def __init__(
        self,
        config: PetasosConfig,
        *,
        on_alert: Callable[[Alert], None] | None = None,
    ) -> None:
```

Internal state:
- `_rule_cooldowns: dict[str, float]` — last fire time per `rule_id|session_id` dedup key. Used for per-rule cooldown enforcement.
- `_per_minute_timestamps: dict[str, deque[float]]` — per-rule timestamp deques for minute-window rate limiting.
- `_per_hour_timestamps: dict[str, deque[float]]` — per-rule timestamp deques for hour-window rate limiting.
- `_ring_buffers: dict[str, deque[tuple[float, str]]]` — ring buffers keyed by `rule_id` (for `cross_session_burst`) or `rule_id|session_id` (for `rapid_fire`). Each entry is `(timestamp, session_id)`. Capacity configurable, default 1000.
- `_pii_ring_buffer: deque[tuple[float, int]]` — dedicated ring buffer for `pii_volume_spike`. Each entry is `(timestamp, entity_count)`. The threshold comparison sums entity counts within the window. Uses the same `maxlen=alert_ring_buffer_capacity`.
- `_alert_count: int`, `_suppressed_count: int`, `_rate_limited_count: int` — diagnostics counters.

**`evaluate(result, session_id, freq_result)` method:**

```python
def evaluate(
    self,
    result: PipelineResult,
    session_id: str | None,
    freq_result: FrequencyUpdateResult | None,
) -> list[Alert]:
```

Runs each of the 5 built-in rules against the result and freq_result. Collects candidate alerts, applies rate limiting and dedup, invokes `on_alert` for each surviving alert, and returns the surviving alerts only (suppressed/rate-limited alerts are not in the return value — they are reflected in the diagnostic counters only).

**5 Built-in Rules:**

Each rule is a private method returning `Alert | None`:

| # | Rule ID | Method | Trigger condition | Severity |
|---|---------|--------|-------------------|----------|
| 1 | `tier_escalation` | `_check_tier_escalation` | `freq_result.tier` differs from `evaluate_tier(freq_result.previous_score, self._config)`. See decision below on decay semantics. | warning (→tier1), high (→tier2), critical (→tier3) |
| 2 | `high_severity_finding` | `_check_high_severity_finding` | Any finding with `severity` at or above the configured threshold (default: `Severity.HIGH`). Comparison uses `Severity` enum ordinal: convert config string via `Severity(self._config.alert_high_severity_threshold)`, then compare using `_SEVERITY_RANK` ordering from `pipeline.py`. | high |
| 3 | `rapid_fire` | `_check_rapid_fire` | ≥N scans from one session in M seconds. **Skipped when `session_id` is None.** Tracked via the ring buffer for this rule. Default N=10, M=60. | warning |
| 4 | `cross_session_burst` | `_check_cross_session_burst` | ≥N distinct sessions trigger findings within M seconds. **Scans with `session_id=None` are excluded** (cannot attribute to a distinct session). Default N=3, M=60. | high |
| 5 | `pii_volume_spike` | `_check_pii_volume_spike` | PII entity count exceeds threshold in a rolling window. PII entity count = number of findings where `finding_type == "pii"` in the current scan. Each `evaluate()` call appends `(timestamp, count)` to `_pii_ring_buffer`; the rule sums counts within the window. Default threshold=20 entities in 300s window. | warning |

**`session_id=None` handling:**

When `session_id` is None:
- `rapid_fire`: skipped entirely (cannot meaningfully detect rapid fire for anonymous scans)
- `cross_session_burst`: None-session scans are excluded from the ring buffer and not counted toward distinct sessions
- Dedup key: uses `rule_id|__none__` — shared cooldown across all anonymous scans (acceptable; anonymous scans have no per-session semantics)
- `tier_escalation`: skipped (requires freq_result, which is None when session_id is None)
- `high_severity_finding` and `pii_volume_spike`: fire normally (not session-dependent)

**Rate limiting:**

Dual-track rate limiting mirrors Drawbridge's pattern:
- **Per-rule cooldown**: Configurable default 60s. After firing, the same `rule_id|session_id` key cannot fire again until the cooldown expires. Uses `time.monotonic()` for drift resistance.
- **Per-minute cap**: Max alerts per rule per minute (default 5). Tracked via timestamp deque; entries older than 60s are evicted.
- **Per-hour cap**: Max alerts per rule per hour (default 20). Same deque pattern, 3600s window.

**Critical exemption:**

Tier 3 escalation alerts (`severity == "critical"`) bypass ALL rate limiting — cooldown, per-minute, per-hour. This is a hardcoded invariant matching the project's "Tier 3 cannot be disabled" principle. No config override.

**Cross-session ring buffer:**

Each rule maintains a ring buffer (`collections.deque(maxlen=capacity)`) storing `(timestamp, session_id)` tuples. Used by `rapid_fire` (per-session count in window) and `cross_session_burst` (distinct-session count in window). Default capacity: 1000. Oldest entries evict automatically via `deque(maxlen=...)`.

**Internal state memory management:**

The dicts `_rule_cooldowns`, `_per_minute_timestamps`, and `_per_hour_timestamps` accumulate keys over time (one per unique `rule_id|session_id` pair). To prevent unbounded growth, `evaluate()` prunes stale entries lazily: after evicting old timestamps from a deque, if the deque is empty, the key is removed from the parent dict. For `_rule_cooldowns`, entries older than `2 * cooldown_seconds` are pruned. This mirrors the passive TTL eviction pattern in `FrequencyTracker.update()` (frequency.py:91-97).

Similarly, `AuditEmitter._sequence_counters` grows per-session. Since the audit emitter holds a reference to config (which has `session_ttl_seconds`), it can lazily prune counters for sessions that haven't emitted in `session_ttl_seconds`. Pruning happens at the start of `emit()`, same as FrequencyTracker's passive eviction. The emitter stores `_last_emit_time: dict[str, float]` alongside the counter (using `time.monotonic()`, matching FrequencyTracker's `last_update` pattern) to enable this.

**Callback error contract:**

Same pattern as AuditEmitter: `on_alert` is called inside try/except. Exceptions are caught and re-raised as `RuntimeError`, surfaced by the pipeline's existing error handler. When used standalone (outside the pipeline), `AuditEmitter.emit()` and `AlertManager.evaluate()` can raise `RuntimeError` — the "never throws" guarantee applies at the Pipeline integration level only.

**Stats properties:**

```python
@property
def alert_count(self) -> int: ...
@property
def suppressed_count(self) -> int: ...
@property
def rate_limited_count(self) -> int: ...
```

Exposed for diagnostics and testing. `suppressed_count` tracks dedup-key suppressions; `rate_limited_count` tracks per-minute/per-hour cap hits.

### Decision: Tier escalation detects decay-through-boundary re-entries

The `tier_escalation` rule compares `evaluate_tier(freq_result.previous_score, self._config)` to `freq_result.tier`. Because `FrequencyUpdateResult.previous_score` is the **decayed** value (see `frequency.py:147`), a session at tier1 (score=16) that decays below tier1_threshold (15) and then re-triggers will fire a none→tier1 alert. This is intentional: decay-through-boundary means the session's threat level genuinely dropped and then rose again — a "re-escalation" is operationally distinct from a sustained tier and worth alerting on. The brief's table at line 100 specifies only two transitions (T1→T2, T2→T3); this spec adds none→tier1 (warning) and maps tier3 to critical to align with the Tier 3 critical exemption invariant that the brief itself mandates ("Tier 3 escalation alerts bypass all rate limiting").

### Decision: `time.monotonic()` for rate limiting, `time.time()` for event timestamps

Rate-limiting windows must be immune to wall-clock adjustments (NTP, DST). `time.monotonic()` is the correct clock for interval tracking. `AuditEvent.timestamp` and `Alert.timestamp` use `time.time()` for human readability in logs and external consumers. The brief explicitly calls this out as a risk mitigation.

### Decision: Alert rule thresholds configurable via PetasosConfig

New config fields (all with sensible defaults matching Drawbridge production values):

```python
# Alert rule thresholds (in PetasosConfig)
alert_cooldown_seconds: float = 60.0
alert_per_minute_cap: int = 5
alert_per_hour_cap: int = 20
alert_high_severity_threshold: Literal["critical", "high", "medium", "low", "info"] = "high"
alert_rapid_fire_count: int = 10
alert_rapid_fire_window_seconds: float = 60.0
alert_cross_session_burst_count: int = 3
alert_cross_session_burst_window_seconds: float = 60.0
alert_pii_volume_threshold: int = 20
alert_pii_volume_window_seconds: float = 300.0
alert_ring_buffer_capacity: int = 1000
```

Validated in `PetasosConfig.__post_init__()` — positive values, finite, etc.

### Decision: Sync callbacks, not async

The brief decided this at spec time. Audit/alerting are side-effects on the diagnostics path. Sync `Callable[[T], None]` avoids polluting the scanner fan-out's `asyncio.gather`. Consumers wrap their own async dispatch if needed.

### 5. Pipeline wiring (`petasos/pipeline.py`)

**Hook signature changes:**

The current stubs:
```python
async def _premium_audit_hook(self, result: PipelineResult, session_id: str | None) -> None:
    pass
async def _premium_alert_hook(self, result: PipelineResult, session_id: str | None) -> None:
    pass
```

The implemented hooks need additional data. Updated signatures:
```python
async def _premium_audit_hook(
    self, result: PipelineResult, session_id: str | None,
    freq_result: FrequencyUpdateResult | None,
) -> None:

async def _premium_alert_hook(
    self, result: PipelineResult, session_id: str | None,
    freq_result: FrequencyUpdateResult | None,
) -> None:
```

The call sites in `_inspect_inner` (lines 414-421) pass `freq_result` through. This is a private API — no external callers.

**Ordering note:** The audit hook fires BEFORE the alert hook (Stage 10 before Stage 11). The audit event captures the `PipelineResult` state before the alert hook runs — any alert-hook errors are NOT reflected in the audit record. This is correct: audit records the scan result, not pipeline plumbing errors.

**Feature gate registration:**

Add entries to `_FEATURE_GATES`:
```python
_FEATURE_GATES: ClassVar[dict[str, str]] = {
    "frequency": "frequency_enabled",
    "escalation": "escalation_enabled",
    "tool_guard": "tool_guard_enabled",
    "audit": "audit_enabled",
    "alerting": "alert_enabled",
}
```

**Premium features manifest:**

Update `_build_premium_features()` to report actual status:
```python
"audit": "unlocked" if active and self._config.audit_enabled else "locked",
"alerting": "unlocked" if active and self._config.alert_enabled else "locked",
```

### Decision: Two-value premium manifest, not three

The brief (line 128) proposed a three-value scheme (`"available"` / `"disabled"` / `"locked"`). This spec follows the existing two-value scheme (`"unlocked"` / `"locked"`) already shipped in PET-6/7/8 for frequency, escalation, tool_guard, and profiles. All existing consumers depend on these values. Adding a third value would require updating all consumers and is a cross-cutting concern beyond PET-9's scope.

**Module instantiation:**

`AuditEmitter` and `AlertManager` are instantiated in `Pipeline.__init__()`, always. They are lightweight (no external deps, no I/O). The hook methods check `_check_premium("audit")` / `_check_premium("alerting")` and short-circuit if disabled or not activated — same pattern as frequency/escalation hooks.

**Callback wiring:**

The `Pipeline` constructor accepts optional `on_audit` and `on_alert` callback parameters. These are passed through to the internal `AuditEmitter` / `AlertManager` instances.

```python
class Pipeline:
    def __init__(
        self,
        scanners: Sequence[Scanner] = (),
        *,
        config: PetasosConfig | None = None,
        profile: str | ResolvedProfile | None = None,
        on_audit: Callable[[AuditEvent], None] | None = None,
        on_alert: Callable[[Alert], None] | None = None,
    ) -> None:
```

### Decision: Instantiate modules eagerly, gate at call time

Mirrors the existing pattern: `FrequencyTracker` is always instantiated in `__init__`, and `_premium_frequency_hook` checks `_check_premium("frequency")` before using it. Same for audit/alerting — modules exist but are dormant until premium is activated AND the per-feature toggle is True.

**Instantiation code (in Pipeline.__init__):**

```python
self._audit_emitter = AuditEmitter(self._config, on_audit=on_audit)
self._alert_manager = AlertManager(self._config, on_alert=on_alert)
```

### Decision: Callbacks on Pipeline, not PetasosConfig

The parent project spec (`petasos-spec.md`) places `on_audit` / `on_alert` as fields on `PetasosConfig`. This spec relocates them to `Pipeline.__init__()` parameters because callables are not JSON-serializable, and `PetasosConfig` supports `to_dict()` / `from_dict()` round-trips. Placing non-serializable callables on a frozen config dataclass that advertises serialization would be a trap. The Pipeline constructor is the correct injection point — it already accepts non-serializable parameters (`scanners`, `profile`).

### 6. Config additions (`petasos/config.py`)

New fields on `PetasosConfig` (all frozen, all validated in `__post_init__`):

```python
# Alerting thresholds
alert_cooldown_seconds: float = 60.0
alert_per_minute_cap: int = 5
alert_per_hour_cap: int = 20
alert_high_severity_threshold: Literal["critical", "high", "medium", "low", "info"] = "high"
alert_rapid_fire_count: int = 10
alert_rapid_fire_window_seconds: float = 60.0
alert_cross_session_burst_count: int = 3
alert_cross_session_burst_window_seconds: float = 60.0
alert_pii_volume_threshold: int = 20
alert_pii_volume_window_seconds: float = 300.0
alert_ring_buffer_capacity: int = 1000

# Audit
audit_verbosity: Literal["minimal", "standard", "verbose"] = "standard"
```

Validation: all numeric fields must be positive and finite. `alert_high_severity_threshold` and `audit_verbosity` use `Literal` types matching the existing `PetasosConfig` convention (`direction`, `fail_mode`, `redaction_mode`) — compile-time type checking via `mypy --strict` rather than runtime-only validation. Additionally, `alert_rapid_fire_count` and `alert_cross_session_burst_count` must be ≤ `alert_ring_buffer_capacity` (otherwise the rule can never fire).

### 7. Premium `__init__.py` exports

Add to `petasos/premium/__init__.py`:
```python
from petasos.premium.audit import AuditEmitter
from petasos.premium.alerting import AlertManager
```

And to `__all__`:
```python
"AuditEmitter",
"AlertManager",
```

The `AuditEvent` and `Alert` types are exported from `petasos._types` (the canonical location for protocol-visible types) and re-exported from `petasos.premium` for convenience.

---

## Test plan

### `tests/test_audit.py` (≥25 tests)

**AuditEvent construction:**
- Frozen dataclass — mutation raises `AttributeError`
- All fields populated correctly from constructor args
- `event_id` is a valid UUID4 hex string

**Verbosity levels:**
- `minimal` payload contains only `safe` and `finding_count`
- `standard` payload additionally contains `findings`, `escalation_tier`, `session_score`
- `verbose` payload additionally contains `scanner_results`, `config_snapshot`, `timing`
- Payload keys at each level are exactly the expected set (no extra, no missing)

**Sequence numbers:**
- First emit for a session produces `sequence_number=0`
- Subsequent emits for the same session produce monotonically increasing sequence numbers
- Different sessions have independent sequence counters
- `session_id=None` uses a dedicated counter (keyed on `"__none__"`)
- No gaps across 100 sequential emits

**Callback behavior:**
- `on_audit=None` — emit completes without error, returns the event
- `on_audit` receives the exact `AuditEvent` that was constructed
- Callback that raises `ValueError` — emitter re-raises as `RuntimeError`
- Callback that raises `Exception` — same wrapping behavior

**Event types:**
- `scan_complete` event emitted for every scan result
- Verify `event_type` field is correctly set

**Edge cases:**
- Empty findings tuple → `finding_count=0` in payload
- `freq_result=None` → `session_score=None` and `escalation_tier=None` in standard/verbose payloads
- Multiple sessions interleaved — sequence numbers tracked independently

### `tests/test_alerting.py` (≥25 tests)

**Alert construction:**
- Frozen dataclass — mutation raises `AttributeError`
- All fields populated correctly

**Rule: `tier_escalation`:**
- Fires when tier crosses none→tier1 (severity: warning)
- Fires when tier crosses tier1→tier2 (severity: high)
- Fires when tier crosses tier2→tier3 (severity: critical)
- Does NOT fire when tier stays the same (e.g., tier1→tier1)
- Does NOT fire when `freq_result` is None

**Rule: `high_severity_finding`:**
- Fires when any finding has severity ≥ threshold (default HIGH)
- Does NOT fire for MEDIUM/LOW/INFO findings only
- Fires for CRITICAL findings
- Configurable threshold: set to MEDIUM → fires on MEDIUM

**Rule: `tier_escalation` — decay re-entry:**
- Session at tier1 that decays below threshold and re-triggers → fires none→tier1 alert
- Session at stable tier1 (no decay below threshold) → does NOT fire

**Rule: `rapid_fire`:**
- Does NOT fire below the count threshold
- Fires at exactly N scans within M seconds
- Does NOT fire if scans are spread beyond the window
- Session-scoped: different sessions don't cross-contaminate
- Skipped when `session_id=None` (no alert, not an error)

**Rule: `cross_session_burst`:**
- Does NOT fire for fewer than N distinct sessions
- Fires when ≥N distinct sessions trigger findings within M seconds
- Works across ≥3 session IDs (explicit brief requirement)
- Duplicate session IDs within the window count as 1
- `session_id=None` scans are excluded from burst detection

**Rule: `pii_volume_spike`:**
- Does NOT fire below the entity threshold
- Fires when PII entity count exceeds threshold in window
- Window expiry: old entries evict correctly

**Rate limiting:**
- Cooldown: same `rule_id|session_id` suppressed within cooldown window
- Per-minute cap: 6th alert within 60s is rate-limited (default cap=5)
- Per-hour cap: 21st alert within 3600s is rate-limited (default cap=20)
- 100 rapid triggers produce bounded output (explicit brief requirement)
- `suppressed_count` and `rate_limited_count` update correctly

**Critical exemption:**
- Tier 3 escalation alert bypasses cooldown
- Tier 3 escalation alert bypasses per-minute cap
- Tier 3 escalation alert bypasses per-hour cap
- Non-critical alerts are still rate-limited normally alongside exempted criticals

**Ring buffer:**
- Buffer respects maxlen capacity — oldest entries evict
- Buffer entries contain correct `(timestamp, session_id)` tuples

**Callback behavior:**
- `on_alert=None` — evaluate completes, returns alerts list
- `on_alert` receives each fired alert
- Callback exception is re-raised as `RuntimeError`

**Stats:**
- `alert_count` reflects total fired alerts
- `suppressed_count` reflects dedup suppressions
- `rate_limited_count` reflects cap-based suppressions

### Integration tests (in existing `tests/test_premium_integration.py`)

- Pipeline with `audit_enabled=True` + premium active → audit hook fires, events emitted
- Pipeline with `alert_enabled=True` + premium active → alert hook fires on triggering input
- Pipeline with audit/alerting disabled → hooks are no-op
- Pipeline with premium inactive → hooks are no-op regardless of config
- `premium_features` manifest shows `"audit": "unlocked"` / `"alerting": "unlocked"` when active and enabled
- `premium_features` manifest shows `"locked"` when disabled or premium inactive
- Callback exception in audit → lands in `result.errors`, pipeline continues
- Callback exception in alerting → lands in `result.errors`, pipeline continues
- Tier 3 termination → critical alert fires, bypasses rate limit (integration)

---

## Test command

```
C:\Users\zioni\AppData\Local\Programs\Python\Python313\python.exe -m pytest tests/test_audit.py tests/test_alerting.py tests/test_premium_integration.py -v && ruff check petasos/premium/audit.py petasos/premium/alerting.py petasos/_types.py petasos/pipeline.py petasos/config.py petasos/premium/__init__.py tests/test_audit.py tests/test_alerting.py && ruff format --check petasos/premium/audit.py petasos/premium/alerting.py petasos/_types.py petasos/pipeline.py petasos/config.py petasos/premium/__init__.py tests/test_audit.py tests/test_alerting.py && mypy --strict petasos/premium/audit.py petasos/premium/alerting.py petasos/_types.py petasos/pipeline.py petasos/config.py
```

---

## Done when

1. `petasos/premium/audit.py` exists with `AuditEmitter` class passing `mypy --strict`.
2. `petasos/premium/alerting.py` exists with `AlertManager` class passing `mypy --strict`.
3. `AuditEvent` and `Alert` types exported from `petasos/_types.py`.
4. Audit events emitted at each verbosity level with correct payload depth (tested).
5. Sequence numbers are monotonic per session with no gaps (tested).
6. All 5 alert rules fire correctly against known trigger sequences (tested).
7. Rate limiting prevents alert storms: 100 rapid triggers → bounded output (tested).
8. Cross-session burst detection works across ≥3 session IDs (tested).
9. Tier 3 alerts bypass rate limit unconditionally (tested).
10. Callbacks invoked correctly; exceptions swallowed gracefully (tested with mock callbacks).
11. Pipeline stubs replaced; audit/alert fire on every scan when enabled (integration tested).
12. ≥50 tests across audit + alerting modules.
13. `ruff check`, `ruff format`, `mypy --strict` pass.

---

## Out of scope

- **Persistence / storage backends** — Petasos emits events; consumers persist them.
- **Dashboard / UI** — Hermes Desktop has no dedicated alert surface (footgun §14); that's a Hermes concern.
- **Network-based alerting** (email, Slack, PagerDuty) — consumer wires their own callback.
- **Alert rule customization beyond thresholds** — custom rule classes are post-v1.
- **Audit log rotation / retention** — consumer's storage layer.
- **Replay / rehydration from audit log** — no event sourcing; audit is write-only from Petasos's perspective.

---

## Deferred (P2+)

- **`__none__` sentinel collision** (edge-cases R2/F-1): A caller passing `session_id="__none__"` as a literal string would collide with the None-session sentinel key. Risk is low (callers control session IDs), but could be hardened with a private object sentinel.
- **Alerts not on PipelineResult** (edge-cases R2/F-7): `evaluate()` returns alerts to the hook, but the hook discards them — alerts are callback-only. Adding an `alerts` field to PipelineResult is a future enhancement if consumers need it.
- **First-scan tier_escalation volume** (edge-cases R2/F-8): Every new session's first flagged scan fires a none→tier1 alert. Per-minute rate limiting bounds the volume, but high session-creation rates may suppress genuine higher-tier alerts. Mitigable by excluding none→tier1 from rate-limit counters in a future iteration.
- **Feature gate key `"alerting"` naming** (conventions R2/F-1): Pre-existing `alert_enabled` config field creates `alerting`/`alert_enabled` asymmetry in `_FEATURE_GATES`. Inherited from PET-6; not worth renaming.
