# PET-7 Brief — Frequency Tracking + Escalation Tiers (Premium)

**Phase:** 4 (Premium tier begins)
**Blocked by:** PET-6 (Pipeline Orchestration)
**Blocks:** PET-8 (Profiles + Tool Call Guard), PET-9 (Audit + Alerting)
**Spec traceability:** PR-1 (frequency tracking), PR-2 (escalation tiers), DC-8 (hot-unlock enforcement)

---

## Problem

The OSS pipeline (PET-1 through PET-6) inspects individual messages statelessly. A sophisticated attacker can distribute malicious content across many low-severity messages within a single session — each message passes inspection, but the aggregate pattern is clearly adversarial. Without session memory, Petasos cannot detect low-and-slow probing, cumulative prompt injection attempts, or escalating abuse patterns.

No existing Python library covers this gap. LLM security libraries (LLM Guard, Pytector, AI Guardian, PIShield) focus on per-message detection. Rate-limiting libraries handle request throttling but not suspicion scoring with configurable decay. This is novel work with a clear Drawbridge reference implementation to adapt from.

## Approach

PET-7 introduces two tightly-coupled premium modules and wires them into the existing pipeline hooks.

### 1. FrequencyTracker (`petasos/premium/frequency.py`)

Per-session exponential decay scoring adapted from Drawbridge's `FrequencyTracker` (`clawmoat-drawbridge-sanitizer/src/frequency/index.ts`). Key behaviors:

- **Exponential decay formula:** `decayed = previous_score * exp((-elapsed * ln(2)) / half_life)` where elapsed is measured via `time.monotonic()`.
- **Rolling window counter** for low-and-slow detection — maintains a `collections.deque` of finding timestamps within a configurable sliding window. When finding count >= rolling threshold, promotes to at least Tier 1 regardless of decay score.
- **Weight matching** — finding types map to configurable weights (exact match, then glob match by longest prefix). No match → weight 0. All weights non-negative.
- **LRU session eviction** — two strategies: passive TTL eviction (stale sessions removed on update), and max-sessions cap (prefer terminated sessions, then oldest by `last_update`). Rate-limited new session creation when at capacity to prevent flood-eviction attacks.
- **Session state dataclass:** `last_score`, `last_update` (monotonic), `rolling_findings` (deque of timestamps), `terminated` (bool).

Python idioms, not TypeScript transliteration: `time.monotonic()` for elapsed time, `dataclasses` for state, `collections.deque` for rolling windows, `math.exp`/`math.log` for decay.

### 2. Escalation Tiers (`petasos/premium/escalation.py`)

Three tiers evaluated after each frequency update:

| Tier | Threshold | Action |
|------|-----------|--------|
| Tier 1 | score > 15.0 | Forced deep inspection (re-scan with lowered thresholds) |
| Tier 2 | score > 30.0 | Enhanced scrutiny, optional block |
| Tier 3 | score > 50.0 | Session termination — **cannot be disabled** |

Thresholds are configurable via `PetasosConfig` (fields already stubbed: `frequency_enabled`, `escalation_enabled`). Tier 3 has a hardcoded floor — setting `tier3_threshold` below the floor either raises `ValueError` or clamps up.

### 3. Pipeline Integration

The pipeline already has stub hooks at stages 6 and 7 (`_premium_frequency_hook`, `_premium_escalation_hook` in `pipeline.py:310-318`). PET-7 replaces these no-ops:

- **Stage 6:** Frequency update runs post-merge, pre-anonymization. Receives merged findings + session_id.
- **Stage 7:** Escalation check runs post-frequency. Evaluates current tier, enforces policy (re-scan / block / terminate).
- **Both gated by license check** — no-op when premium is inactive.

`PipelineResult` gains three fields: `escalation_tier: str | None`, `session_score: float | None`, `premium_features: dict[str, str] | None` (maps feature name → "locked"/"unlocked" status).

### 4. License Gate Scaffold

Implement `_check_premium(feature_name: str) -> bool` as a method on `Pipeline`. For PET-7, this is a simple flag check against `self._premium_active`. Real JWT validation (PET-10 scope) plugs into this method later without changing callers.

### 5. Config Additions

Extend `PetasosConfig` with validated premium fields:

```python
frequency_half_life_seconds: float = 60.0
rolling_window_seconds: float = 300.0
rolling_threshold: int = 10
tier1_threshold: float = 15.0
tier2_threshold: float = 30.0
tier3_threshold: float = 50.0
max_sessions: int = 10_000
session_ttl_seconds: float = 3600.0
max_new_sessions_per_minute: int = 60
```

Validation: thresholds strictly ascending, tier3 floor enforced, all numeric values positive and finite.

## Prior Art

**Drawbridge reference implementation** (`clawmoat-drawbridge-sanitizer/src/frequency/index.ts`, 328 lines) is the direct ancestor. Key patterns to preserve: the two-part decay+rolling detection, LRU eviction with rate limiting, weight matching by exact-then-glob, frozen static results for disabled/rate-limited states. Key divergences: Python `time.monotonic()` instead of `Date.now()`, `dataclasses` instead of interfaces, `deque` instead of array filtering, no deep-freeze (frozen dataclasses serve the same purpose).

**No competing Python library** covers session-aware frequency tracking with exponential decay for security pipelines. Per-message detectors (LLM Guard, Pytector) and rate limiters exist but don't compose a scoring + escalation system.

---

## Decisions Carried Forward

1. **Petasos is uncoupled from Drawbridge.** Own repo, own ticket prefix, own release cadence, own threat model. PET-7 adapts Drawbridge's frequency tracker design but shares no code, no rule package, no cross-runtime conformance requirement. (Spec conformance test uses a documented reference output sequence, not Drawbridge's test suite.)

2. **Detection is free, session intelligence is paid.** FrequencyTracker and escalation tiers are premium-only. The pipeline always contains the code paths; license state is checked at execution time (DC-8: hot-unlock enforcement).

3. **Tier 3 cannot be disabled.** Hardcoded floor on the termination threshold. No config override, no profile override, no API bypass. This is a security invariant.

4. **Pipeline never throws.** Frequency/escalation errors are caught and appended to `PipelineResult.errors`. A broken tracker degrades gracefully; it never crashes the pipeline.

5. **Premium hot-unlock means no pipeline reconstruction.** `Pipeline` is constructed once. `petasos.activate(key)` flips internal state; premium hooks start executing on the next `inspect()` call. PET-7 builds the scaffold; PET-10 adds real JWT validation.

6. **Frozen exports.** Default thresholds, built-in weight maps, and static result objects are immutable (frozen dataclasses, defensive copies on getters).

---

## Done When

- [ ] `FrequencyTracker` computes exponential decay correctly — scores match a documented reference output sequence for a fixed input (test fixture, not Drawbridge's suite).
- [ ] Exponential decay verified: score halves after one half-life interval (within floating-point tolerance).
- [ ] Rolling window counter promotes to Tier 1 when finding count >= threshold within window, even if decay score is below Tier 1.
- [ ] Weight matching: exact match takes priority over glob; longest-prefix glob wins; no-match → weight 0.
- [ ] Tier 3 cannot be disabled — setting `tier3_threshold` below floor raises `ValueError` or clamps to floor.
- [ ] Session eviction under memory pressure: >1,000 sessions → oldest evicted (prefer terminated), no crash.
- [ ] Rate limiting: new session creation rejected when at capacity and exceeding per-minute limit.
- [ ] Pipeline integration: premium stages run when `_premium_active` is True, skip cleanly when False.
- [ ] `PipelineResult` gains `escalation_tier`, `session_score`, and `premium_features` fields. Existing tests unbroken (fields default to `None`).
- [ ] `_check_premium()` scaffold works as a flag check; replacing it later (PET-10) requires no caller changes.
- [ ] Config validation: thresholds strictly ascending, tier3 floor enforced, all numerics positive and finite.
- [ ] Pipeline never throws — frequency/escalation errors land in `PipelineResult.errors`, not exceptions.
- [ ] `PipelineResult.premium_features` manifest populated correctly — maps feature name → "locked"/"unlocked" per current license state.
- [ ] >= 40 tests covering frequency scoring, decay math, rolling window, eviction, escalation tiers, pipeline integration, and config validation.
- [ ] All existing tests pass (`pytest`), no regressions.

---

## Out of Scope

- **Real JWT validation** — PET-10 scope. PET-7 uses a boolean flag scaffold.
- **Profiles** — PET-8 scope. FrequencyTracker accepts weight maps but doesn't resolve them from profile names.
- **Tool call guard** — PET-8 scope. Escalation tiers report state; they don't enforce tool-level blocking.
- **Audit emission** — PET-9 scope. Frequency/escalation produce data; audit hooks remain stubs.
- **Alerting rules** — PET-9 scope. Alert hooks remain stubs.
- **Cross-runtime conformance with Drawbridge** — Petasos is uncoupled. Reference output conformance uses its own documented fixture, not Drawbridge's test suite.
- **Network calls** — no telemetry, no license server, no remote validation. Everything is local.
- **Anonymization changes** — anonymization pipeline (PET-5/6) is stable; PET-7 doesn't modify it.
