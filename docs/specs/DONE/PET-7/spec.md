# PET-7 — Frequency Tracking + Escalation Tiers (Premium)

## Goal

Ship the `FrequencyTracker` and escalation tier evaluator — the first two premium modules that give Petasos session memory. When this lands, a single `await pipeline.inspect()` call accumulates per-session suspicion scores via exponential decay, detects low-and-slow probing via rolling window counters, and escalates through three enforcement tiers (Tier 3 = session termination, cannot be disabled). The pipeline hooks stubbed in PET-6 gain real implementations gated by a license flag scaffold.

## Scope

### New files

| File | Purpose |
|------|---------|
| `petasos/premium/__init__.py` | Package marker — exports `FrequencyTracker`, `FrequencyUpdateResult`, `EscalationResult`, `evaluate_tier` |
| `petasos/premium/frequency.py` | `FrequencyTracker` — exponential decay + rolling window + LRU eviction + rate limiting |
| `petasos/premium/escalation.py` | `evaluate_tier()` function + `EscalationResult` dataclass + tier constants + `TIER3_FLOOR` |
| `tests/test_frequency.py` | FrequencyTracker unit tests (>=25) |
| `tests/test_escalation.py` | Escalation evaluator + tier enforcement tests (>=10) |
| `tests/test_premium_integration.py` | Pipeline integration tests for premium hooks (>=10) |

### Modified files

| File | Change |
|------|--------|
| `petasos/_types.py` | Add `escalation_tier`, `session_score`, `premium_features` fields to `PipelineResult` |
| `petasos/config.py` | Add 10 validated premium config fields (thresholds, half-life, rolling window, session management) |
| `petasos/pipeline.py` | Replace hook no-ops with real implementations; add `_check_premium()`, `_frequency_tracker`, `_build_premium_features()`, `_build_result()`; add `activate()`/`deactivate()` instance methods; update PipelineResult construction sites 2+3 in `_inspect_inner()` (site 1 outer handler intentionally keeps `None` defaults) |
| `petasos/__init__.py` | Export `FrequencyTracker`, `FrequencyUpdateResult` |

### New public methods on `Pipeline`

| Method | Purpose |
|--------|---------|
| `activate()` | Set `self._premium_active = True` — enables premium hooks on next `inspect()` (D12) |
| `deactivate()` | Set `self._premium_active = False` — disables premium hooks on next `inspect()` (D12) |

### Files left alone

- `petasos/normalize.py` — consumed as-is
- `petasos/scanners/*.py` — consumed as-is; no scanner changes
- `tests/test_pipeline.py`, `tests/test_config.py`, `tests/test_finding_merge.py` — existing tests must continue to pass without modification (new PipelineResult fields default to `None`)

## Decisions

### D1 — `time.monotonic()` for elapsed time, not `time.time()`

Drawbridge uses `Date.now()` (wall-clock). Python's `time.monotonic()` is immune to wall-clock adjustments (NTP jumps, DST, manual `date` changes). Decay calculation depends on accurate elapsed-time measurement — monotonic is the correct choice. All session timestamps use monotonic time.

### D2 — `dataclasses` for session state, not dicts

Drawbridge uses plain objects/interfaces. Python equivalent: `@dataclass` with typed fields. `SessionState` is a mutable dataclass (score and timestamp update in place). `FrequencyUpdateResult` and `EscalationResult` are frozen (immutable return values). Frozen dataclasses serve the same purpose as Drawbridge's `Object.freeze()`.

### D3 — `collections.deque` for rolling window, not list filtering

Drawbridge filters the rollingFindings array on every update (O(n) scan + allocation). Python's `deque` provides O(1) `append` and efficient left-side pruning. Rolling window entries are pruned by timestamp on each update — oldest entries that fall outside the window are popped from the left.

### D4 — FrequencyTracker is a plain class, not an async context manager

FrequencyTracker holds no async resources (no files, no sockets, no background tasks). `update()` is synchronous — it performs only math, dict lookups, and deque operations. The pipeline hooks that call it are async (because the hook signature is async), but the tracker itself doesn't need async.

### D5 — Escalation evaluation is a standalone function; tracker embeds minimal tier knowledge

Drawbridge couples tier evaluation entirely into the tracker. Petasos exposes `evaluate_tier(score, config)` as a standalone function for independent testing and PET-8 profile overrides. However, `FrequencyTracker.update()` *also* calls `evaluate_tier` internally (step 9 in §5.1) because it needs the tier to set `terminated=True` for Tier 3 sessions. The returned `FrequencyUpdateResult.tier` is populated by this internal call. The escalation *module* (`evaluate_escalation()` with its `EscalationResult` / action mapping) remains fully decoupled — only the bare `evaluate_tier()` function is called inside the tracker.

### D6 — Tier 3 floor is enforced via `ValueError`, not silent clamping

The brief allows either `ValueError` or clamp-up. `ValueError` is explicit — the caller knows their config was rejected, rather than silently getting a different threshold than they requested. The floor constant `TIER3_FLOOR = 30.0` is defined in `escalation.py` and re-exported.

### D7 — Pipeline instance state for per-call premium results

Premium hooks store their results as instance attributes (`self._last_freq_result`, `self._last_escalation_tier`), reset at the start of each `_inspect_inner()` call. PipelineResult construction reads from these. This is not thread-safe for concurrent `inspect()` calls — Petasos targets sequential in-process use by Hermes Agent, matching Drawbridge's "NOT thread-safe, designed for single-threaded event loop" contract.

### D8 — Weight map uses Petasos rule ID namespace

Drawbridge weights reference `drawbridge.prompt_injection.*` etc. Petasos rules use `petasos.syntactic.injection.*`, `petasos.syntactic.structural.*`, `petasos.syntactic.encoding.*`. Default weights map to Petasos's own rule taxonomy. Custom weights from config follow the same exact-then-glob matching.

### D9 — `_check_premium()` is a simple flag check for PET-7

The license gate scaffold method `_check_premium(feature_name: str) -> bool` checks only `self._premium_active`. PET-10 replaces the body with JWT validation (claim-level feature checks) without changing callers. The method exists now so all premium code paths go through a single gate from day one.

### D10 — Threshold comparison uses `>=`, not `>`

The brief's "done when" criteria use `>` (e.g., "score > tier1_threshold"). The spec uses `>=` to match Drawbridge's behavior (`score >= threshold`). Rationale: a score landing exactly on a threshold should escalate — the threshold is the boundary at which the tier activates, not a value below which it holds. `>=` is the conservative choice (escalates slightly sooner at the boundary).

### D11 — `safe` is independent of escalation tier

Tier 3 termination does not force `safe=False`. The `safe` field reflects the content analysis only (findings with `HIGH` or `CRITICAL` severity). A session can be Tier 3 terminated (accumulated suspicion) while the current message has no high-severity findings — `safe=True`, `escalation_tier="tier3"`, `terminated=True` is a valid state. The consumer (Hermes Agent) is responsible for combining `safe` and `escalation_tier` into its enforcement decision.

### D12 — `activate()`/`deactivate()` are Pipeline instance methods

CLAUDE.md documents a planned `petasos.activate(key)` module-level API. PET-7 implements `pipeline.activate()` / `pipeline.deactivate()` as **instance methods** because the premium flag is per-Pipeline state. PET-10 (JWT validation) may add a module-level convenience wrapper, but the instance methods are the canonical API for PET-7. The scope table is updated to reflect this.

## Design

### 5.1 FrequencyTracker (`petasos/premium/frequency.py`)

```python
@dataclass
class SessionState:
    last_score: float
    last_update: float  # time.monotonic()
    rolling_findings: deque[float]  # monotonic timestamps
    terminated: bool = False

@dataclass(frozen=True)
class FrequencyUpdateResult:
    previous_score: float
    current_score: float
    tier: str  # "none", "tier1", "tier2", "tier3"
    terminated: bool

DISABLED_RESULT = FrequencyUpdateResult(
    previous_score=0.0, current_score=0.0, tier="none", terminated=False
)
RATE_LIMITED_RESULT = FrequencyUpdateResult(
    previous_score=0.0, current_score=0.0, tier="none", terminated=False
)

class FrequencyTracker:
    def __init__(self, config: PetasosConfig) -> None: ...
    def update(self, session_id: str, rule_ids: Sequence[str]) -> FrequencyUpdateResult: ...
    def get_state(self, session_id: str) -> SessionState | None: ...
    def reset(self, session_id: str) -> None: ...
    def clear(self) -> None: ...  # removes all sessions AND all creation timestamps
    @property
    def size(self) -> int: ...
```

**Constructor:**
- Extracts frequency-relevant fields from `PetasosConfig` (half-life, rolling window, thresholds, session limits, weight map).
- Pre-partitions the weight map into exact matches (`dict[str, float]`) and glob entries (list of `(prefix, weight)` sorted by prefix length descending, most specific first). **Partitioning rule:** keys ending with `".*"` are glob entries; the prefix is the key with trailing `".*"` removed (e.g., `"petasos.syntactic.injection.*"` → prefix `"petasos.syntactic.injection"`). All other keys are exact matches. Keys containing `"*"` in a non-terminal position raise `ValueError`.
- Validates all weights are non-negative and finite. Raises `ValueError` on invalid weights.
- Initializes `self._sessions: dict[str, SessionState]` and `self._creation_timestamps: deque[float]`.

**`update(session_id, rule_ids)` algorithm:**

1. **Passive TTL eviction** — collect stale session IDs (where `now - state.last_update > session_ttl_seconds`) in a list, then delete them in a second pass. Two-pass avoids `RuntimeError` from dict mutation during iteration. O(n) full scan, sub-ms for <10k sessions.

2. **Get or create session** — look up `session_id` in `self._sessions`. If missing:
   - **Prune creation timestamps:** before checking the rate limit, pop entries older than 60 seconds from the left of `self._creation_timestamps` (deque is ordered by insertion time). This bounds the deque to at most `max_new_sessions_per_minute` entries, preventing unbounded growth.
   - Check rate limit: if `len(self._sessions) >= max_sessions` AND `len(self._creation_timestamps) >= max_new_sessions_per_minute`, return `RATE_LIMITED_RESULT`.
   - Create `SessionState(last_score=0.0, last_update=now, rolling_findings=deque(), terminated=False)`.
   - Record creation timestamp in `self._creation_timestamps`.

3. **Enforce max-sessions cap** — if new session was just created and `len(self._sessions) > max_sessions`: evict one session. Prefer terminated sessions first, then oldest by `last_update`. Never evict the session that was just created.

4. **Terminated sessions** — if `state.terminated`, return immediately with `tier="tier3"`, `terminated=True`, score unchanged.

5. **Compute weight** — for each `rule_id` in `rule_ids`, call `_match_weight(rule_id)`. Sum all weights.

6. **Decay previous score** — `elapsed = max(0.0, now - state.last_update)` (clamp to non-negative; protects against `math.exp` overflow if monotonic clock has sub-microsecond jitter producing negative elapsed); `decayed = state.last_score * math.exp((-elapsed * math.log(2)) / half_life_seconds)`.

7. **Update score** — `previous_score = decayed`; `current_score = decayed + total_weight`.

8. **Update rolling window** — first, prune entries older than `rolling_window_seconds` from the left of the deque (always, regardless of `rule_ids`). Then, if `rule_ids` is non-empty, append `now` to `state.rolling_findings`. Pruning before tier evaluation ensures stale entries don't inflate the rolling count during decay-only heartbeats.

9. **Evaluate tier** — call `evaluate_tier(current_score, config)`. If tier is `"none"` but `len(state.rolling_findings) >= rolling_threshold`, promote to `"tier1"` (low-and-slow detection).

10. **Update state** — set `state.last_score = current_score`, `state.last_update = now`. If tier is `"tier3"`, set `state.terminated = True`.

11. **Return** `FrequencyUpdateResult(previous_score, current_score, tier, state.terminated)`.

**`_match_weight(finding_type)` algorithm:**
1. Exact match in `self._exact_weights` → return weight.
2. Glob match: iterate `self._glob_weights` (sorted by prefix length descending). If `finding_type.startswith(prefix + ".")`, return weight.
3. No match → return `0.0`.

**Weight map defaults** (in `PetasosConfig` or as a module constant — see §5.5):

```python
DEFAULT_FREQUENCY_WEIGHTS: dict[str, float] = {
    "petasos.syntactic.injection.*": 10.0,
    "petasos.syntactic.structural.*": 5.0,
    "petasos.syntactic.encoding.*": 3.0,
}
```

These are intentionally coarse — PET-8 profiles will provide fine-grained per-rule weights. The defaults cover the three MinimalScanner categories with escalating suspicion: injection attempts are highest-weight, structural anomalies medium, encoding tricks lowest.

**Static results** — `DISABLED_RESULT` and `RATE_LIMITED_RESULT` are module-level frozen dataclass instances. Defensive copies not needed since frozen dataclasses are immutable.

### 5.2 Escalation Tiers (`petasos/premium/escalation.py`)

```python
TIER3_FLOOR: float = 30.0

@dataclass(frozen=True)
class EscalationResult:
    tier: str  # "none", "tier1", "tier2", "tier3"
    action: str  # "none", "deep_inspect", "enhanced_scrutiny", "terminate"
    threshold_crossed: float | None  # the threshold value that was exceeded, or None

def evaluate_tier(score: float, config: PetasosConfig) -> str:
    """Map a suspicion score to an escalation tier string.

    Uses >= (not >) for threshold comparison — see Decision D10.
    """
    if score >= config.tier3_threshold:
        return "tier3"
    if score >= config.tier2_threshold:
        return "tier2"
    if score >= config.tier1_threshold:
        return "tier1"
    return "none"

def evaluate_escalation(score: float, config: PetasosConfig) -> EscalationResult:
    """Full escalation evaluation — tier + action + metadata."""
    ...
```

**Tier → action mapping:**

| Tier | Action | Meaning |
|------|--------|---------|
| `"none"` | `"none"` | No escalation |
| `"tier1"` | `"deep_inspect"` | Forced deep inspection (re-scan with lowered thresholds) |
| `"tier2"` | `"enhanced_scrutiny"` | Enhanced scrutiny, optional block |
| `"tier3"` | `"terminate"` | Session termination — cannot be disabled |

`TIER3_FLOOR = 30.0` — the minimum allowable value for `tier3_threshold`. Config validation in `PetasosConfig.__post_init__` enforces this.

### 5.3 Config Additions (`petasos/config.py`)

Add 10 new fields to `PetasosConfig`:

```python
# Frequency tracking
frequency_half_life_seconds: float = 60.0
frequency_weights: dict[str, float] | None = None  # None → use DEFAULT_FREQUENCY_WEIGHTS
rolling_window_seconds: float = 300.0
rolling_threshold: int = 10

# Escalation thresholds
tier1_threshold: float = 15.0
tier2_threshold: float = 30.0
tier3_threshold: float = 50.0

# Session management
max_sessions: int = 10_000
session_ttl_seconds: float = 3600.0
max_new_sessions_per_minute: int = 60
```

**Validation in `__post_init__`:**

1. `frequency_half_life_seconds` — must be positive and finite.
2. `rolling_window_seconds` — must be positive and finite.
3. `rolling_threshold` — must be a positive integer.
4. Thresholds strictly ascending: `tier1_threshold < tier2_threshold < tier3_threshold`. Raises `ValueError` if not.
5. `tier3_threshold >= TIER3_FLOOR` (30.0). Raises `ValueError` if below.
6. `max_sessions` — must be a positive integer.
7. `session_ttl_seconds` — must be positive and finite.
8. `max_new_sessions_per_minute` — must be a positive integer.
9. If `frequency_weights` is not `None`, all values must be non-negative and finite.

**Serialization:** `to_dict()` and `from_dict()` require no changes for `frequency_weights` — dicts serialize natively to/from JSON. The defensive copy in `__post_init__` creates a new dict object, but value equality is preserved across round-trips. No special handling needed (unlike `pii_entities` which needs list→tuple conversion).

**Frozen dataclass compatibility:** `frequency_weights` is `dict[str, float] | None`. Dicts are mutable, but the frozen constraint only prevents reassigning the attribute — it doesn't deep-freeze the dict. Because `PetasosConfig` is `@dataclass(frozen=True)`, the defensive copy must use `object.__setattr__` in `__post_init__`, matching the existing `pii_entities` pattern:

```python
def __post_init__(self) -> None:
    ...  # existing validation
    if self.frequency_weights is not None:
        object.__setattr__(self, "frequency_weights", dict(self.frequency_weights))
```

Pipeline also deep-copies config (existing D6 from PET-6), so the original dict is safe.

### 5.4 Pipeline Integration (`petasos/pipeline.py`)

**Constructor changes:**

Import at the top of `pipeline.py` (not deferred inside `__init__`), since `petasos/premium/` is pure Python with no heavy deps:

```python
from petasos.premium.frequency import FrequencyTracker, FrequencyUpdateResult
```

`FrequencyUpdateResult` is imported for the type annotation on `self._last_freq_result`. No `TYPE_CHECKING` guard needed — the import is unconditional because the module is lightweight.

```python
def __init__(self, scanners, *, config=None) -> None:
    ...  # existing code
    # FrequencyTracker — always constructed (even when premium is inactive).
    # update() is only called when _check_premium("frequency") returns True.
    self._frequency_tracker = FrequencyTracker(self._config)

    # Per-call premium state (reset at start of each _inspect_inner)
    self._last_freq_result: FrequencyUpdateResult | None = None
    self._last_escalation_tier: str | None = None
```

**`_inspect_inner()` changes:**

At the top of `_inspect_inner`, reset per-call state:
```python
self._last_freq_result = None
self._last_escalation_tier = None
```

**PipelineResult construction sites.** Current `pipeline.py` (PET-6) has three `PipelineResult(...)` construction sites:

1. **Outer exception handler** (`inspect()`, line 183) — catches any exception from `_inspect_inner()`. Constructs `PipelineResult(safe=False, findings=(), errors=(...))` with all premium fields as `None`. This is intentional: no premium processing ran, so `None` defaults are correct. **Do not use `_build_result()` here** — the method reads `self._last_freq_result` which may be in an inconsistent state after an exception.
2. **Initial construction** (`_inspect_inner()`, line 279) — the normal result path.
3. **Stage-12 rebuild** (`_inspect_inner()`, line 301) — fires when audit/alert hooks add errors post-construction.

Sites 2 and 3 must include the premium fields to prevent them reverting to `None` on rebuild.

Extract a helper to avoid duplication:

```python
def _build_result(
    self,
    *,
    safe: bool,
    findings: tuple[ScanFinding, ...],
    sanitized_content: str | None,
    scanner_results: tuple[ScanResult, ...],
    errors: tuple[str, ...],
) -> PipelineResult:
    return PipelineResult(
        safe=safe,
        findings=findings,
        sanitized_content=sanitized_content,
        scanner_results=scanner_results,
        errors=errors,
        escalation_tier=self._last_escalation_tier,
        session_score=(
            self._last_freq_result.current_score
            if self._last_freq_result is not None
            else None
        ),
        premium_features=self._build_premium_features(),
    )
```

Sites 2 and 3 call `self._build_result(...)` instead of constructing `PipelineResult` directly. This guarantees the rebuild path at stage 12 always includes premium fields. Site 1 (outer exception handler) continues to construct `PipelineResult` directly with `None` premium fields — this is the catastrophic-failure path.

**Hook implementations:**

```python
async def _premium_frequency_hook(
    self, findings: tuple[ScanFinding, ...], session_id: str | None
) -> None:
    if not self._check_premium("frequency"):
        return
    if not self._config.frequency_enabled:
        return  # double-gate: license activates all premium; per-feature config allows selective disable
    if session_id is None:
        return  # frequency tracking requires a session
    rule_ids = [f.rule_id for f in findings]
    self._last_freq_result = self._frequency_tracker.update(session_id, rule_ids)

async def _premium_escalation_hook(
    self, findings: tuple[ScanFinding, ...], session_id: str | None
) -> None:
    if not self._check_premium("escalation"):
        return
    if not self._config.escalation_enabled:
        return
    if self._last_freq_result is None:
        return  # no frequency data to evaluate

    self._last_escalation_tier = self._last_freq_result.tier
```

Note: the tier is already computed inside `FrequencyTracker.update()` (step 9 in §5.1) because the tracker needs the tier to determine session termination. The escalation hook reads the tier from the frequency result and stores it for PipelineResult — no import needed. `evaluate_escalation()` (which adds the action mapping) is available via `petasos.premium.escalation` for callers who need the full `EscalationResult`, but the pipeline only needs the tier string.

**If `session_id` is `None`:** both hooks return immediately with no work. Frequency tracking is session-scoped — a message without a session ID cannot be tracked. This is a graceful no-op, not an error.

**`safe` is independent of escalation tier (D11).** The `safe` field on `PipelineResult` reflects content analysis only (whether any finding has `HIGH` or `CRITICAL` severity). Tier 3 termination does not force `safe=False` — a terminated session can still yield `safe=True` if the current message has no high-severity findings. The consumer is responsible for combining `safe` and `escalation_tier` into enforcement decisions.

**`_check_premium()` scaffold:**

```python
def _check_premium(self, feature_name: str) -> bool:
    return self._premium_active
```

**`_build_premium_features()` manifest:**

```python
from types import MappingProxyType

def _build_premium_features(self) -> MappingProxyType[str, str]:
    active = self._premium_active
    return MappingProxyType({
        "frequency": "unlocked" if active and self._config.frequency_enabled else "locked",
        "escalation": "unlocked" if active and self._config.escalation_enabled else "locked",
        "profiles": "locked",
        "tool_guard": "locked",
        "audit": "locked",
        "alerting": "locked",
    })
```

### 5.5 PipelineResult Extensions (`petasos/_types.py`)

Add three fields with `None` defaults (backwards-compatible):

```python
from types import MappingProxyType

@dataclass(frozen=True)
class PipelineResult:
    safe: bool
    findings: tuple[ScanFinding, ...]
    sanitized_content: str | None = None
    scanner_results: tuple[ScanResult, ...] = ()
    errors: tuple[str, ...] = ()
    # Premium fields (PET-7)
    escalation_tier: str | None = None
    session_score: float | None = None
    premium_features: MappingProxyType[str, str] | None = None
```

**Immutability:** `premium_features` uses `MappingProxyType` (read-only dict view) rather than a bare `dict` to prevent callers from mutating the manifest on a frozen dataclass. `_build_premium_features()` constructs a plain dict and wraps it in `MappingProxyType(...)` before returning. External code that constructs `PipelineResult` with `premium_features=None` (the default) is unaffected.

**Serialization note:** `MappingProxyType` is not JSON-serializable via `json.dumps()` or `dataclasses.asdict()`. Consumers who need to serialize `PipelineResult` must convert: `dict(result.premium_features)` before serializing. This trade-off (immutability over convenience) is intentional — the manifest is read-only by design.

Existing code that constructs `PipelineResult` without these fields continues to work — all three default to `None`.

Note: `PipelineResult`'s docstring currently references "PET-6 extends this with premium fields." This is incorrect — PET-7 adds the premium fields. The docstring will be updated to reference PET-7.

### 5.6 Public API (`petasos/__init__.py`)

Add to exports:

```python
from petasos.premium.frequency import FrequencyTracker, FrequencyUpdateResult
```

Add `"FrequencyTracker"` and `"FrequencyUpdateResult"` to `__all__`.

The escalation module exports (`evaluate_tier`, `evaluate_escalation`, `EscalationResult`, `TIER3_FLOOR`) are available via `petasos.premium.escalation` but not re-exported from the top-level `petasos` namespace — they're internal implementation details of the pipeline, not consumer-facing API.

### 5.7 Premium Hot-Unlock Flow

No pipeline reconstruction on key change. `Pipeline` is constructed once with a `FrequencyTracker`. `pipeline.activate()` (D12 — instance method for PET-7) flips `self._premium_active = True`. The next `inspect()` call hits the `_check_premium()` gate and the hooks execute. `pipeline.deactivate()` flips the flag back; hooks become no-ops again on the next call. Session state in the `FrequencyTracker` is preserved across activate/deactivate cycles.

For PET-7, the activation method is a simple setter:

```python
def activate(self) -> None:
    self._premium_active = True

def deactivate(self) -> None:
    self._premium_active = False
```

PET-10 replaces `activate()` with `activate(key: str)` + JWT validation.

## Test plan

### test_frequency.py (>=25 tests)

**Decay math (5):**
- Score halves after exactly one half-life interval (within 1e-9 tolerance)
- Score decays to near-zero after many half-lives
- Zero elapsed time → no decay (score unchanged)
- Decay with zero initial score → stays zero
- Multiple updates with known weights produce reference output sequence

**Weight matching (5):**
- Exact match takes priority over glob
- Glob match: longest prefix wins
- No match → weight 0.0
- Multiple rule_ids → weights summed
- Empty rule_ids list → weight 0, score only decays

**Rolling window (4):**
- Findings within window counted correctly
- Findings outside window pruned on update
- Rolling threshold promotes to tier1 even if decay score is below tier1
- Empty rolling window after all entries expire

**Session eviction (4):**
- TTL eviction: stale sessions removed on update
- Max-sessions cap: oldest evicted (prefer terminated)
- Eviction never removes the session being updated
- >1000 sessions: no crash, eviction works correctly

**Rate limiting (3):**
- New session rejected when at capacity and over per-minute limit
- New session accepted when under capacity
- Rate limit window rolls forward (old timestamps pruned)

**Edge cases (4):**
- Terminated session returns immediately with tier3
- `session_id` lookup for unknown session → `None`
- `reset()` removes a session
- `clear()` removes all sessions and resets creation timestamps

### test_escalation.py (>=10 tests)

**Tier evaluation (4):**
- Score below tier1 → "none"
- Score between tier1 and tier2 → "tier1"
- Score between tier2 and tier3 → "tier2"
- Score at or above tier3 → "tier3"

**Tier 3 floor (3):**
- Config with `tier3_threshold < TIER3_FLOOR` raises `ValueError`
- Config with `tier3_threshold == TIER3_FLOOR` accepted (if thresholds are ascending)
- `TIER3_FLOOR` constant is 30.0

**Escalation result (3):**
- tier1 → action "deep_inspect"
- tier2 → action "enhanced_scrutiny"
- tier3 → action "terminate"

### test_premium_integration.py (>=12 tests)

**Pipeline hooks (5):**
- Premium inactive: hooks are no-ops, `PipelineResult.escalation_tier` is `None`
- Premium active + frequency enabled: `session_score` populated after inspect
- Premium active + escalation enabled: `escalation_tier` populated
- Premium active but `session_id=None`: hooks skip gracefully, no error
- Frequency hook exception lands in `PipelineResult.errors`, not raised

**PipelineResult fields (4):**
- `escalation_tier` defaults to `None` (existing tests unbroken)
- `session_score` defaults to `None`
- `premium_features` manifest populated correctly (all "locked" when inactive)
- Tier 3 terminated session with benign content: `safe=True`, `escalation_tier="tier3"` (D11)

**Config validation (3):**
- Thresholds not strictly ascending → `ValueError`
- All numeric premium fields positive and finite → accepted
- Negative half-life → `ValueError`

### Existing test suites

All existing tests in `test_pipeline.py`, `test_config.py`, `test_finding_merge.py` must pass without modification. The new `PipelineResult` fields default to `None` so existing constructors are unaffected.

## Test command

```
python -m pytest tests/test_frequency.py tests/test_escalation.py tests/test_premium_integration.py tests/test_pipeline.py tests/test_config.py -v && python -m mypy --strict petasos/premium/frequency.py petasos/premium/escalation.py petasos/pipeline.py petasos/config.py petasos/_types.py && python -m ruff check petasos/premium/ petasos/pipeline.py petasos/config.py petasos/_types.py
```

## Done when

- [ ] `FrequencyTracker` computes exponential decay correctly — scores match a documented reference output sequence for a fixed input (test fixture, not Drawbridge's suite).
- [ ] Exponential decay verified: score halves after one half-life interval (within floating-point tolerance).
- [ ] Rolling window counter promotes to Tier 1 when finding count >= threshold within window, even if decay score is below Tier 1.
- [ ] Weight matching: exact match takes priority over glob; longest-prefix glob wins; no-match → weight 0.
- [ ] Tier 3 cannot be disabled — setting `tier3_threshold` below floor raises `ValueError`.
- [ ] Session eviction under memory pressure: >1,000 sessions → oldest evicted (prefer terminated), no crash.
- [ ] Rate limiting: new session creation rejected when at capacity and exceeding per-minute limit.
- [ ] Pipeline integration: premium stages run when `_premium_active` is True, skip cleanly when False.
- [ ] `PipelineResult` gains `escalation_tier`, `session_score`, and `premium_features` fields. Existing tests unbroken (fields default to `None`).
- [ ] `_check_premium()` scaffold works as a flag check; replacing it later (PET-10) requires no caller changes.
- [ ] Config validation: thresholds strictly ascending, tier3 floor enforced, all numerics positive and finite.
- [ ] Pipeline never throws — frequency/escalation errors land in `PipelineResult.errors`, not exceptions.
- [ ] `PipelineResult.premium_features` manifest populated correctly — maps feature name → "locked"/"unlocked" per current license state.
- [ ] >= 42 tests covering frequency scoring, decay math, rolling window, eviction, escalation tiers, pipeline integration, and config validation.
- [ ] All existing tests pass (`pytest`), no regressions.

## Out of scope

- **Real JWT validation** — PET-10 scope. PET-7 uses a boolean flag scaffold.
- **Profiles** — PET-8 scope. FrequencyTracker accepts weight maps but doesn't resolve them from profile names.
- **Tool call guard** — PET-8 scope. Escalation tiers report state; they don't enforce tool-level blocking.
- **Audit emission** — PET-9 scope. Frequency/escalation produce data; audit hooks remain stubs.
- **Alerting rules** — PET-9 scope. Alert hooks remain stubs.
- **Cross-runtime conformance with Drawbridge** — Petasos is uncoupled. Reference output conformance uses its own documented fixture, not Drawbridge's test suite.
- **Network calls** — no telemetry, no license server, no remote validation. Everything is local.
- **Anonymization changes** — anonymization pipeline (PET-5/6) is stable; PET-7 doesn't modify it.
- **Thread safety for concurrent `inspect()` calls** — Petasos targets sequential in-process use by Hermes Agent, matching Drawbridge's single-threaded contract.
- **Forced deep-inspection re-scan logic** — Tier 1 action is `"deep_inspect"` (marker only). The actual re-scan-with-lowered-thresholds behavior is a PET-8/pipeline-enhancement concern; PET-7 sets the flag.

## Deferred (P2+)

- **DISABLED_RESULT vs RATE_LIMITED_RESULT identity** (P2) — both are identical frozen instances. Callers who need to distinguish rate-limiting from disabled state should use `result is RATE_LIMITED_RESULT` (object identity). Document this convention in `frequency.py` module docstring.
- **`tier` field as bare `str`** (P2) — `FrequencyUpdateResult.tier` and `EscalationResult.tier` use bare `str`. A `Literal["none", "tier1", "tier2", "tier3"]` type annotation would provide static type checking. Defer to PET-8 when profiles may add custom tier names.
- **`premium_features` format diverges from `petasos-spec.md`** (P2) — `petasos-spec.md` describes `premium_features` as a list of feature dicts. PET-7 uses a `dict[str, str]` mapping feature names to status strings. The dict form is simpler and sufficient. `petasos-spec.md` will be updated to reflect the dict format when PET-7 ships.
- **Manifest pre-declares PET-8/9/10 features** (P3) — `_build_premium_features()` includes entries for `profiles`, `tool_guard`, `audit`, and `alerting` (all `"locked"`). This pre-declares features that ship in later tickets. Rationale: the manifest should reflect the full premium feature set from day one so consumers can display a stable feature grid. New features transition from `"locked"` to `"unlocked"` as their tickets ship.
- **FrequencyTracker always constructed in OSS installations** (P3) — `FrequencyTracker` is instantiated in Pipeline.__init__ even when no premium license is active. Acceptable overhead: the constructor is cheap (dict + deque, no ML deps), and constructing lazily would add conditional logic to every `inspect()` call. The `_check_premium()` gate prevents any work in `update()`.
- **`frequency_weights` glob key convention** (P2) — the `".*"` suffix in glob weight keys (e.g., `"petasos.syntactic.injection.*"`) is semantically meaningful: `_match_weight` strips the trailing `".*"` and uses `startswith(prefix + ".")` for matching. Document this convention in `frequency.py`.
- **Empty `rule_ids` acts as decay heartbeat** (P3) — calling `update(session_id, [])` decays the score without adding weight. This is intentional and useful for time-decay probing, but undocumented. Add a one-line note to `update()` docstring.
- **Default `tier2=30` equals `TIER3_FLOOR=30`** (P4) — valid configuration (thresholds are strictly ascending: 15 < 30 < 50), but tight. No action needed; users who want more headroom can adjust.
- **`FrequencyUpdateResult.tier` embeds escalation knowledge** (P3) — partially contradicts D5's "separation" claim. D5 has been softened to acknowledge this intentional minimal coupling (see revised D5).
- **Eviction by oldest allows attacker to evict high-suspicion sessions** (P2) — eviction prefers terminated then oldest, without considering suspicion score. An attacker steadily creating new sessions can evict legitimate high-suspicion sessions. The rate limiter provides a speed bump. Known limitation for PET-7; a score-weighted eviction policy is a possible future enhancement.
- **Empty `frequency_weights={}` silently disables scoring** (P2) — `{}` passes validation but all weights resolve to 0.0, making frequency tracking a no-op. Acceptable for PET-7 since `None` is the documented way to get defaults. A future validation rule could reject empty dicts explicitly.
- **Rate limit window hardcoded to 60 seconds** (P3) — the `_creation_timestamps` pruning window is hardcoded to 60s in the algorithm, matching the `max_new_sessions_per_minute` naming. Extract as `_RATE_LIMIT_WINDOW_SECONDS = 60` module constant.
- **Config validation tests placed in integration file** (P2) — PET-7 puts config validation tests in `test_premium_integration.py` rather than `test_config.py`. This groups all premium tests together. Existing `test_config.py` tests (covering PET-6 fields) are unmodified.
- **`petasos.premium` subpackage public surface** (P3) — `premium/__init__.py` exports `FrequencyTracker`, `FrequencyUpdateResult`, `EscalationResult`, `evaluate_tier`, but section 5.6 calls escalation exports "internal implementation details." Clarify that `petasos.premium` is a public subpackage for consumers who need direct access; the top-level `petasos` namespace is the primary API surface.
