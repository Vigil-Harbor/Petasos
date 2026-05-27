# Petasos Security Hardening Checklist

Audit artifact for v1.0.0 release. Verifies existing code against Drawbridge security hardening categories.

**Audited commit:** Post PET-10 merge (`44639fe`) on `master`.
**Date:** 2026-05-26

---

## 1. Input Validation

| Check | Status | Evidence |
|-------|--------|----------|
| Config fields type-checked | PASS | `PetasosConfig.__post_init__` validates all fields: type checks, range checks (`0.0 <= threshold <= 1000.0`), finite checks (`math.isfinite`). Invalid values raise `ValueError`. |
| Input normalization | PASS | `normalize.py` applies NFKC normalization, zero-width character stripping, homoglyph mapping, and RTL override detection before content reaches ML scanners. |
| Payload size limit | PASS | `MinimalScanner._check_structural()` enforces `max_payload_bytes` (default 524,288). Oversized payloads produce `CRITICAL` severity findings. |
| JSON depth limit | PASS | `MinimalScanner._check_json_depth()` enforces `max_json_depth` (default 10). Excessive nesting produces `CRITICAL` severity findings. |
| Binary content rejection | PASS | `MinimalScanner._check_structural()` detects control characters (`\x01-\x08`, `\x0e-\x1f`) and produces `CRITICAL` findings. |

## 2. Error Handling

| Check | Status | Evidence |
|-------|--------|----------|
| Pipeline never throws | PASS | `Pipeline.inspect()` wraps `_inspect_inner()` in `try/except Exception` (pipeline.py line 301-320). All exceptions returned as `PipelineResult(safe=False, errors=(...))`. |
| Scanner isolation | PASS | `_scan_one()` wraps each scanner call in `try/except` with `asyncio.wait_for` timeout (pipeline.py line 127-148). Scanner crashes produce `ScanResult(error=str(exc))`, not pipeline-level failures. |
| Premium hook isolation | PASS | Each premium hook (frequency, escalation, audit, alerting) is individually wrapped in `try/except` (pipeline.py lines 404-461). Hook errors append to `errors` list without stopping the pipeline. |
| Fail-mode enforcement | PASS | `_compute_safe()` enforces three modes: `degraded` (all ML fail → block), `open` (ML fail → pass), `closed` (any ML fail → block). Default is `degraded`. |

## 3. Secrets Management

| Check | Status | Evidence |
|-------|--------|----------|
| Local-only license validation | PASS | `LicenseValidator` uses Ed25519/EdDSA with a bundled public key (`premium/license.py`). Zero network calls at runtime. |
| Keys never logged | PASS | `AuditEmitter.emit()` records `finding_count`, `safe`, `escalation_tier`, `session_score` — never license keys, raw tokens, or PII content. Payload is constructed from `PipelineResult` fields only (`premium/audit.py`). |
| No key persistence | PASS | License state is held in-memory (`_license_state`, `_license_claims`). No disk write, no environment mutation. `deactivate()` clears both fields. |
| Hash key isolation | PASS | `hash_key` for HMAC anonymization is passed through `PetasosConfig` and used only in `_HmacSha256Operator.operate()`. Never logged, never stored beyond the function scope. |

## 4. Frozen Exports

| Check | Status | Evidence |
|-------|--------|----------|
| Immutable data types | PASS | `ScanFinding`, `ScanResult`, `PipelineResult`, `Position`, `AuditEvent`, `Alert`, `LicenseClaims` — all `@dataclass(frozen=True)`. |
| Immutable config copies | PASS | `PetasosConfig.copy()` returns a new instance via `replace()`. Pipeline stores `config.copy()` (pipeline.py line 161). |
| Immutable built-in profiles | PASS | `BUILT_IN_PROFILES` uses `MappingProxyType`. `ResolvedProfile` is `frozen=True`. `suppress_rules` is `frozenset`. |
| Immutable rule taxonomy | PASS | `RULE_TAXONOMY` in `minimal.py` is `frozenset[str]`. Pattern lists are module-level constants. |
| Premium features manifest | PASS | `_build_premium_features()` returns `MappingProxyType` (pipeline.py line 254). |

## 5. Rate Limiting

| Check | Status | Evidence |
|-------|--------|----------|
| Alert per-minute cap | PASS | `AlertManager._per_minute_cap` (default 10). Exceeding increments `_rate_limited_count`. |
| Alert per-hour cap | PASS | `AlertManager._per_hour_cap` (default 50). Exceeding increments `_rate_limited_count`. |
| Alert cooldown dedup | PASS | `AlertManager._rule_cooldowns` dict. Same `(rule_id, session_id)` within cooldown window → `_suppressed_count += 1`, alert not fired. |
| Alert ring buffer | PASS | `AlertManager._ring_buffer` with configurable capacity. Oldest alerts evicted when full. |
| Frequency max sessions | PASS | `FrequencyTracker._max_sessions` (default 10,000). Exceeded → oldest session evicted. |
| Frequency session TTL | PASS | `FrequencyTracker._session_ttl`. Expired sessions cleaned on access. |
| Frequency new-session rate | PASS | `FrequencyTracker._new_session_per_minute_limit`. Exceeded → new session creation rejected. |

## 6. Tier 3 Invariant

| Check | Status | Evidence |
|-------|--------|----------|
| Floor enforced | PASS | `TIER3_FLOOR = 30.0` in `config.py`. `PetasosConfig.__post_init__` enforces `tier3_threshold >= TIER3_FLOOR`. |
| Cannot be disabled | PASS | `escalation.py` — `evaluate_tier()` always checks `tier3_threshold`. No config flag to skip tier3 evaluation. |
| Terminated stays terminated | PASS | `FrequencyTracker.update()` — terminated sessions return immediately with `terminated=True` without score update. |

## 7. Platform Footguns (Hermes Desktop)

| Footgun | Status | Rationale |
|---------|--------|-----------|
| 4c — File tool bypass | N/A | Petasos is an in-process library. It does not dispatch file operations, shell commands, or subprocess calls. All processing is in-memory text transformation. |
| 5 — Hook shebang divergence | N/A | Petasos ships zero hook scripts, zero shell scripts, zero executables. It is a pure Python library imported by the host process. |
| 9 — Signal handling divergence | N/A | Petasos does not register signal handlers (`signal.signal()`). Lifecycle management is the host process's responsibility (Hermes). Future work must not add signal handlers without revisiting this assessment. |

---

## Summary

All 28 checks pass. Petasos v1.0.0 meets the Drawbridge security hardening baseline with three platform footguns documented as N/A (in-process library with no subprocess, hook, or signal handler surface).
