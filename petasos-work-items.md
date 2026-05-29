# Petasos — Plane Work Items

> Source spec: `petasos-spec.md` (2026-05-24)
> Target project: **PET** (`REDACTED-PLANE-UUID`)
> Granularity: hybrid — phase-level for small/coupled phases, sub-phase for parallelizable ones

## ID Map

Plane auto-assigns sequence IDs. PET-2 is a parent container; PET-3/4/5 are its children (the scanner wrappers). All IDs below match Plane.

| Plane ID | Name | Phase |
|----------|------|-------|
| PET-1 | Repo Bootstrap + Core Types + MinimalScanner + Normalization | 1 |
| PET-2 | OSS Scanner Wrappers (parent) | 2 |
| PET-3 | LlmGuardScanner Wrapper (child of PET-2) | 2 |
| PET-4 | LlamaFirewallScanner Wrapper (child of PET-2) | 2 |
| PET-5 | PresidioScanner Wrapper + Anonymization (child of PET-2) | 2 |
| PET-6 | Pipeline Orchestration (OSS tier complete) | 3 |
| PET-7 | Frequency Tracking + Escalation Tiers (Premium) | 4 |
| PET-8 | Profiles + Tool Call Guard (Premium) | 5 |
| PET-9 | Audit Trails + Alert Rules (Premium) | 6 |
| PET-10 | JWT License Validation + Premium Wiring | 7a |
| PET-11 | Integration Testing + Performance Benchmarks | 7b |
| PET-12 | Wiki + Docs + PyPI Release | 8 |
| PET-13 | Petasos Console — Config & Observability Surface | 9 |
| PET-14 | Red-team security review (instruction set + cross-model pass) | — |
| PET-15–74 | Red-team remediation (1:1 with finding IDs; child of PET-14, each blocks PET-12) | — |

## PET-14 remediation backlog (PET-15–74)

Posted from `docs/security/red-team-findings.md` after Bucket B cross-model review (2026-05-26). **60 work items**, one per refuted/confirmed finding; parent **PET-14**; each **blocks PET-12** (release).

| Priority | Findings | Plane |
|----------|----------|-------|
| Urgent | RT-075, FREQ-03, GUARD-03 | PET-15, PET-43, PET-48 |
| High | SYN-02/08, PIPE-02/04/07, CFG-03, SCAN-04/05/07, FREQ-02, GUARD-01/02/05, AUD-03, ALRT-01/02, PROF-04 | see `docs/security/plane-remediation-index.md` |

Full index: `docs/security/plane-remediation-posted.json`.

## Platform Impact Map

Hermes Desktop ships on macOS and Windows (.exe). The macOS path is well-documented; see `docs/platform/hermes-desktop-footguns.md` for the Windows-specific report. Items below are annotated with which footgun sections apply.

| Item | Footgun §§ | What to watch |
|------|-----------|---------------|
| PET-1 | None | Pure Python library, no platform surface |
| PET-3/4/5 | §9 | If scanners spawn subprocesses, handle Windows signal model (SIGTERM unreliable) |
| PET-6 | §1, §2, §3 | Config must be top-level key (`petasos:`), not under `model:`. File tools bypass terminal sandbox — pipeline hooks must cover both dispatch paths. Config is snapshot-on-start. |
| PET-7 | §3 | Session boundaries are frozen at start — frequency state doesn't survive config reload |
| PET-8 | §1, §4, §10 | ToolCallGuard must intercept `file` tools AND `terminal` tools (§1). Shell hooks add 100-200ms on Windows via Git Bash (§4a). Evaluate hook vs plugin vs guardrails extension (§10). |
| PET-9 | §14 | No dedicated security alert UI channel — block reasons flow inline in chat. Audit events need a separate surface if frontend wants them outside the conversation. |
| PET-10 | §6, §13 | `PETASOS_LICENSE_KEY` matches Hermes's `*_KEY` sanitization pattern (free Unicode stripping). Must be added to env blocklist so it doesn't leak into terminal subprocesses. |
| PET-11 | §4c, §5, §9 | Integration tests must cover Windows/Git Bash path. Hook script shebangs resolve differently under MINGW64. Process lifecycle tests need both signal models. |
| PET-13 | §2, §3, §14 | Config editor writes to `petasos:` namespace (§2). Session-restart notice on config changes (§3). Console provides the dedicated alert/observability surface Hermes lacks (§14). |

## Reference Sources

- **Drawbridge syntactic rules (17 patterns):** `internal-sanitizer/src/validation/index.ts` → `SYNTACTIC_RULES` export. PET-1 ports these to Python regex. The source has injection patterns, role-switch triggers, capability grants, and structural checks (oversized payload, excessive depth, binary content).
- **Drawbridge FrequencyTracker:** `internal-sanitizer/src/frequency/index.ts`. PET-7 adapts this to Python idioms (don't transliterate TypeScript).

---

## PET-1 · Repo Bootstrap + Core Types + MinimalScanner + Normalization

**Phase:** 1 (Foundation)
**Blocked by:** nothing — first item
**Blocks:** PET-2 (scanner wrappers), PET-6 (pipeline)

### Scope

Stand up the greenfield repo and implement every core abstraction that downstream items depend on:

1. **Repo scaffolding** — `pyproject.toml` (Hatch build backend), extras for each scanner backend (`llm-guard`, `llamafirewall`, `presidio`, `all`), `ruff` config, `mypy --strict`, `pytest`, GitHub Actions CI stub, `.gitignore`.
2. **Core types** — `Scanner` protocol, `ScanResult`, `ScanFinding`, `Direction` (literal `"inbound" | "outbound"`), `PipelineResult`, `Severity` enum/literal. All types in `petasos/_types.py`.
3. **MinimalScanner** — 17 syntactic regex rules ported from Drawbridge's pre-filter (source: `internal-sanitizer/src/validation/index.ts` → `SYNTACTIC_RULES`). Pure Python, zero ML deps. Each rule has a category tag and severity. NFKC-normalized input before matching.
4. **Input normalization module** — NFKC normalization, zero-width character stripping, confusable homoglyph mapping (Unicode confusables table or curated subset), RTL override detection. Exposed as `petasos.normalize(text) -> NormalizedText`.

### Key files to produce

```
petasos/
├── __init__.py          # public API re-exports
├── _types.py            # Scanner protocol, ScanResult, ScanFinding, Direction, PipelineResult, Severity
├── normalize.py         # normalization functions
├── scanners/
│   ├── __init__.py
│   └── minimal.py       # MinimalScanner (17 rules)
├── py.typed             # PEP 561 marker
pyproject.toml
ruff.toml
.gitignore
tests/
├── test_types.py
├── test_normalize.py
└── test_minimal_scanner.py
```

### Gate criteria

- [ ] `MinimalScanner` detects all 17 rule categories against a fixed test corpus
- [ ] Normalization strips zero-width chars, maps confusable homoglyphs, detects RTL overrides
- [ ] `mypy --strict` clean, `ruff` clean
- [ ] ≥50 tests passing
- [ ] `pip install -e .` in a clean Python 3.11 venv succeeds (base install, no ML deps)

### Spec traceability

FR-1 (Scanner protocol), FR-3 (pipeline never throws — error types), FR-4 (config types), NFR-1 (Python 3.11+), NFR-4 (zero required ML deps at install)

---

## PET-2 · OSS Scanner Wrappers (parent)

**Phase:** 2
**Blocked by:** PET-1
**Blocks:** PET-6

Parent container. Children PET-3, PET-4, PET-5 are fully independent — three CC squads can work simultaneously after PET-1 lands.

---

## PET-3 · LlmGuardScanner Wrapper

**Phase:** 2 (child of PET-2)
**Blocked by:** PET-1
**Blocks:** PET-6
**Parallel with:** PET-4, PET-5

### Scope

Implement `LlmGuardScanner` in `petasos/scanners/llm_guard.py`. Wraps `llm-guard`'s PromptInjection, Toxicity, BanTopics, InvisibleText, and Secrets scanners. Lazy-loads the `llm_guard` package on first use — if not installed, raises a clear `ImportError` with install instructions. Maps `llm-guard` output to `ScanResult`/`ScanFinding` types. Handles backend failures gracefully per fail-mode policy (for now, catch exceptions and return an errored `ScanResult`).

Constructor takes:
- `threshold: float = 0.85` — confidence threshold for injection detection
- `enable_toxicity: bool = False`
- `enable_secrets: bool = False`
- `enable_invisible_text: bool = True`
- `enable_ban_topics: bool = False`, `ban_topics: list[str] = []`

### Gate criteria

- [ ] Integration tests pass against real `llm-guard` backend (not mocked) with a 20-message corpus
- [ ] `pip install petasos[llm-guard]` in clean venv succeeds
- [ ] Correct `ScanFinding` objects produced (scanner_name, finding_type, severity, confidence populated)
- [ ] Fail-open verified: `import llm_guard` fails → scanner returns errored result, no crash
- [ ] ≥15 tests

### Spec traceability

FR-1 (pluggable backends), NFR-4 (extras-based install)

---

## PET-4 · LlamaFirewallScanner Wrapper

**Phase:** 2 (child of PET-2)
**Blocked by:** PET-1
**Blocks:** PET-6
**Parallel with:** PET-3, PET-5

### Scope

Implement `LlamaFirewallScanner` in `petasos/scanners/llama_firewall.py`. Wraps LlamaFirewall's PromptGuard 2 (jailbreak detection), AlignmentCheck (chain-of-thought auditor), and CodeShield (static analysis for unsafe code gen). Lazy-load pattern. Maps output to `ScanResult`.

Constructor takes:
- `enable_prompt_guard: bool = True`
- `enable_alignment_check: bool = False` — CoT auditor, heavier
- `enable_code_shield: bool = False`

### Gate criteria

- [ ] Integration tests pass against real `llamafirewall` backend with a 20-message corpus
- [ ] `pip install petasos[llamafirewall]` in clean venv succeeds
- [ ] Correct `ScanFinding` objects produced
- [ ] Fail-open verified
- [ ] ≥15 tests

### Spec traceability

FR-1 (pluggable backends), NFR-4 (extras-based install)

---

## PET-5 · PresidioScanner Wrapper + Anonymization

**Phase:** 2 (child of PET-2)
**Blocked by:** PET-1
**Blocks:** PET-6
**Parallel with:** PET-3, PET-4

### Scope

Implement `PresidioScanner` in `petasos/scanners/presidio.py`. Wraps `presidio-analyzer` AnalyzerEngine for PII detection and `presidio-anonymizer` AnonymizerEngine for redaction. Two responsibilities:

1. **Detection** — run Presidio analyzer, map `RecognizerResult` entries to `ScanFinding` objects with entity type, position, confidence.
2. **Anonymization** — expose an `anonymize(text, findings, mode)` function that takes PII findings and applies the configured operator (`redact`, `replace`, `hash`, `mask`). HMAC-SHA256 hashing when `mode="hash"` and a key is provided. This function is called by the pipeline (PET-6), not by the scanner itself.

Constructor takes:
- `entities: list[str] = ["DEFAULT"]` — Presidio entity types to detect
- `language: str = "en"`
- `score_threshold: float = 0.35`

### Gate criteria

- [ ] Integration tests pass against real `presidio-analyzer` with a 20-message corpus containing known PII
- [ ] Anonymization produces correct redaction for each operator mode (redact, replace, hash, mask)
- [ ] HMAC-SHA256 hash mode produces deterministic, correlatable hashes
- [ ] `pip install petasos[presidio]` in clean venv succeeds
- [ ] Fail-open verified
- [ ] ≥20 tests (detection + anonymization)

### Spec traceability

FR-1 (pluggable backends), FR-2 (PII detection and anonymization), NFR-4 (extras-based install)

---

## PET-6 · Pipeline Orchestration (OSS tier complete)

**Phase:** 3
**Blocked by:** PET-1, PET-2 (all scanner wrappers)
**Blocks:** PET-7, PET-8, PET-9

### Scope

Implement the `Pipeline` class in `petasos/pipeline.py`. This is the central orchestrator and the item that makes the OSS tier shippable.

Pipeline stages (OSS tier):
1. **Normalize** — call `petasos.normalize()` on input text
2. **Syntactic pre-filter** — run `MinimalScanner` (always, deterministic baseline)
3. **Fan-out scan** — run all configured scanners concurrently via `asyncio.gather` with exception isolation per scanner
4. **Merge findings** — collect findings from all scanners, deduplicate overlapping positions (prefer higher-confidence finding), compute aggregate severity
5. **Fail-mode enforcement** — implement `open`/`closed`/`degraded` logic (NFR-3)
6. **Anonymize** — if PII findings present and anonymization enabled, call Presidio anonymizer
7. **Return `PipelineResult`** — `safe`, `findings`, `sanitized_content`, scanner metadata

Also implement `PetasosConfig` dataclass (§3.4 of spec) — every field from the spec, JSON-serializable, with validation.

The pipeline must **never throw** — all errors caught, wrapped in result. This is a hard invariant.

Premium stage hooks: the pipeline should have clearly marked insertion points where premium stages (frequency, escalation, audit, alerting) will be wired in by PET-7/8/9. Use a simple pattern (e.g., `await self._premium_frequency_hook(result)` that is a no-op until premium modules are wired).

### Gate criteria

- [ ] Pipeline runs end-to-end with 0, 1, 2, or 3 scanners configured
- [ ] Concurrent execution verified (scanners run in parallel, not sequentially)
- [ ] Finding deduplication works for overlapping position ranges
- [ ] Fail-mode `degraded`: partial scanner failure → pass; all ML failure → block; syntactic always runs
- [ ] Fail-mode `open`: any failure → pass
- [ ] Fail-mode `closed`: any failure → block
- [ ] Anonymization produces correct redaction with HMAC correlation
- [ ] Pipeline never throws — all error paths return valid `PipelineResult`
- [ ] Latency budget met: syntactic-only < 5ms, single ML < 100ms, full pipeline < 250ms (CPU)
- [ ] `PetasosConfig` serializes to/from JSON correctly
- [ ] ≥60 tests (pipeline + config + merge + fail-mode)
- [ ] **OSS tier is shippable** — tag `v0.1.0-alpha.1`

### Spec traceability

FR-3 (pipeline orchestration), FR-4 (configuration-first), FR-5 (input + output scanning), NFR-2 (latency budget), NFR-3 (fail-mode degraded)

---

## PET-7 · Frequency Tracking + Escalation Tiers (Premium)

**Phase:** 4
**Blocked by:** PET-6
**Blocks:** PET-8, PET-9

### Scope

Implement two tightly-coupled premium modules:

1. **FrequencyTracker** (`petasos/premium/frequency.py`) — per-session exponential decay scoring with configurable half-life (default 60s). Rolling window counters. LRU-based session eviction under memory pressure. Adapt from Drawbridge's `FrequencyTracker` (source: `internal-sanitizer/src/frequency/index.ts`) — use Python idioms, `time.monotonic()`, dataclasses. Don't transliterate TypeScript.

2. **Escalation tiers** (`petasos/premium/escalation.py`) — three tiers evaluated after each frequency update:
   - Tier 1 (score > 15): forced deep inspection (re-scan with lowered thresholds)
   - Tier 2 (score > 30): enhanced scrutiny, optional block
   - Tier 3 (score > 50): session termination — **cannot be disabled** (hardcoded floor)

3. **Wire into Pipeline** — frequency update runs post-scan, escalation check runs post-frequency. Both gated by license check (no-op when premium is inactive). `PipelineResult` gains `escalation_tier` and `session_score` fields.

4. **License gate scaffold** — implement the hot-unlock check point: `_check_premium(feature_name) -> bool`. For now, a simple flag or mock JWT check. The real JWT validation (PET-10 scope) plugs in here.

### Gate criteria

- [ ] Frequency scores match a reference output sequence (document the reference in a test fixture)
- [ ] Exponential decay verified: score decays correctly over time intervals
- [ ] Tier 3 cannot be disabled — test that setting `tier3_threshold` below floor raises or is clamped
- [ ] Session eviction under memory pressure: >1000 sessions → oldest evicted, no crash
- [ ] Pipeline integration: premium stages run when flag is on, skip cleanly when off
- [ ] `PipelineResult.premium_features` manifest populated correctly (locked/unlocked status)
- [ ] ≥40 tests (frequency + escalation + pipeline integration)

### Spec traceability

PR-1 (frequency tracking), PR-2 (escalation tiers), DC-8 (hot-unlock enforcement)

---

## PET-8 · Profiles + Tool Call Guard (Premium)

**Phase:** 5
**Blocked by:** PET-7
**Blocks:** PET-10
**Parallel with:** PET-9 (independent modules, both depend on PET-7)

### Scope

1. **Profile system** (`petasos/premium/profiles.py`) — 5 built-in profiles loaded from bundled JSON config: `general`, `customer-service`, `code-generation`, `research`, `admin`. Each profile adjusts: scanner thresholds, PII entity sensitivity, rule severity overrides, escalation tier thresholds. Custom profiles via dict or dataclass. `ProfileResolver` selects the active profile.

2. **ToolCallGuard** (`petasos/premium/guard.py`) — evaluates tool calls before execution. Inputs: tool name, tool parameters, current session state (frequency score, escalation tier). Logic:
   - Normalize tool name (case, namespace stripping)
   - Check tier-aware policy: Tier 1 → warn, Tier 2 → block unless allowlisted, Tier 3 → block all
   - Scan parameter content through the pipeline (recursive call with `direction="outbound"`)
   - Return `GuardResult` with `allowed`, `reason`, `findings`

3. **Wire profiles into Pipeline** — profile selection at pipeline construction or per-call override. Profile adjustments applied before scanner fan-out.

### Gate criteria

- [ ] All 5 built-in profiles load correctly from bundled JSON
- [ ] Each profile demonstrably adjusts scanner thresholds (test with MinimalScanner threshold changes)
- [ ] Custom profile overrides built-in values correctly
- [ ] ToolCallGuard blocks at Tier 2/3, warns at Tier 1
- [ ] Parameter scanning routes through pipeline and produces findings
- [ ] Tool name normalization handles edge cases (case, namespace, whitespace)
- [ ] ≥50 tests (profiles + guard)

### Spec traceability

PR-3 (profile-driven tuning), PR-4 (tool call policy guard)

---

## PET-9 · Audit Trails + Alert Rules (Premium)

**Phase:** 6
**Blocked by:** PET-6 (pipeline result structure), PET-7 (frequency/escalation data)
**Blocks:** PET-10
**Parallel with:** PET-8 (independent modules, both depend on PET-7)

### Scope

1. **AuditEmitter** (`petasos/premium/audit.py`) — verbosity-gated structured audit events. Three verbosity levels: `minimal` (scan result only), `standard` (result + findings + tier), `verbose` (everything including raw scanner output). Each event is a typed dataclass with: `event_id`, `timestamp`, `session_id`, `event_type`, `payload`, `sequence_number`. Tamper-evident ordering via monotonic sequence numbers per session. Emission via callback (`on_audit: Callable[[AuditEvent], None]`).

2. **AlertManager** (`petasos/premium/alerting.py`) — 5 built-in alert rules:
   - Tier escalation (session crosses a tier boundary)
   - High-severity finding (any finding above threshold)
   - Rapid-fire scanning (N scans in M seconds from one session)
   - Cross-session burst (N sessions trigger findings within M seconds)
   - PII volume spike (PII entity count exceeds threshold in window)

   Rate limiting per rule (configurable cooldown). Critical exemption: Tier 3 alerts bypass rate limiting. Emission via callback (`on_alert: Callable[[Alert], None]`).

3. **Wire into Pipeline** — audit emission after every scan, alert evaluation after finding merge + escalation. Both gated by premium license check.

### Gate criteria

- [ ] Audit events emitted at each verbosity level with correct payload depth
- [ ] Sequence numbers are monotonic per session, no gaps
- [ ] All 5 alert rules fire correctly against known trigger sequences
- [ ] Rate limiting prevents alert storms (test: 100 rapid triggers → limited output)
- [ ] Cross-session burst detection works across ≥3 session IDs
- [ ] Critical exemption: Tier 3 alerts bypass rate limit
- [ ] Callbacks invoked correctly (test with mock callbacks)
- [ ] ≥50 tests (audit + alerting)

### Spec traceability

PR-5 (structured audit trails), PR-6 (alert rules)

---

## PET-10 · JWT License Validation + Premium Wiring

**Phase:** 7a (Integration + Hardening)
**Blocked by:** PET-7, PET-8, PET-9
**Blocks:** PET-11

### Scope

Implement the real license validation that replaces the scaffold from PET-7:

1. **JWT validation** (`petasos/premium/license.py`) — validate signed JWT locally using a bundled public key. JWT payload: `tier` (string), `expiry` (ISO timestamp), `customer_id` (string). No network required at runtime. Expose `petasos.activate(key: str)` and `PETASOS_LICENSE_KEY` env var as activation paths.

2. **Hot-unlock behavior** — activation sets pipeline-wide state. Next `pipeline.inspect()` call runs premium stages. No pipeline reconstruction. Deactivation (expired key, explicit `deactivate()`) reverts to OSS-only behavior on next call.

3. **`premium_features` manifest** — every `PipelineResult` includes a list of premium features with their lock status, so frontends can render upgrade CTAs.

4. **Security hardening pass** — defensive copies on all config objects, frozen built-in profiles/rules/configs (`deepcopy` + `__setattr__` override or `frozen=True` dataclasses), mutation prevention on `ScanResult` and `PipelineResult`.

### Gate criteria

- [ ] Valid JWT → premium stages activate on next `inspect()` call
- [ ] Expired JWT → premium stages deactivate, OSS stages still run
- [ ] Invalid signature → rejected, OSS-only
- [ ] `petasos.activate(key)` and env var both work
- [ ] `result.premium_features` manifest is correct for locked and unlocked states
- [ ] Frozen configs: mutating a built-in profile raises `AttributeError` or similar
- [ ] Defensive copies: modifying returned config/result doesn't mutate pipeline internals
- [ ] ≥25 tests (license + hardening)

### Spec traceability

DC-8 (hot-unlock via JWT), NFR-5 (security hardening)

---

## PET-11 · Integration Testing + Performance Benchmarks

**Phase:** 7b (Integration + Hardening)
**Blocked by:** PET-10
**Blocks:** PET-12

### Scope

End-to-end validation that all modules compose correctly and the package meets its performance and compatibility contracts.

1. **Hermes integration smoke test** — verify `import petasos` works inside a module that also imports Hermes's deps (spaCy, transformers). Check for version conflicts in the dep graph. Write a minimal Hermes-style integration fixture (import petasos, create pipeline, scan a message).

2. **Full-pipeline E2E tests** — all premium features enabled, multiple scanners, frequency escalation through all 3 tiers, audit + alerting callbacks firing, tool call guard blocking. Cover the complete happy path and the complete failure path.

3. **Performance benchmarks** — measure and document latency for:
   - Syntactic-only (MinimalScanner): target < 5ms
   - Single ML scanner: target < 100ms
   - Full pipeline (2 ML + Presidio + all premium): target < 250ms
   - All on CPU, Python 3.11, document hardware specs

4. **Coverage report** — run `pytest --cov`, verify ≥90% line coverage on `pipeline`, `frequency`, `guard`, `audit`, `alerting` modules. Document any excluded lines with justification.

### Gate criteria

- [ ] `import petasos` works alongside Hermes deps (no version conflict)
- [ ] Full E2E test: inbound message → 3 scanners → frequency → Tier 2 escalation → audit event → alert fired → anonymized output
- [ ] Full E2E failure test: all ML scanners error → degraded mode blocks → correct result
- [ ] Latency benchmarks documented and within budget
- [ ] ≥300 total tests across all modules
- [ ] ≥90% line coverage on core modules
- [ ] Security hardening checklist from Drawbridge applied and documented
- [ ] Tag `v1.0.0` candidate

### Spec traceability

NFR-2 (latency budget), NFR-5 (test coverage), Phase 7 gates

---

## PET-12 · Wiki + Docs + PyPI Release

**Phase:** 8
**Blocked by:** PET-11, PET-13, PET-15–74
**Blocks:** nothing — final item

### Scope

1. **Wiki pages** — create `projects/petasos/` directory in `vigil-harbor-wiki`:
   - `architecture.md` — Scanner protocol, pipeline stages, premium modules, JWT validation
   - `state.md` — per-claim anchored status (per wiki SCHEMA.md)
   - `filemap.md` — annotated file listing

2. **Decision entry** — `decisions/2026-05-24-petasos-oss-compose.md` documenting the compose-over-build decision (wrapping LLM Guard + LlamaFirewall + Presidio instead of building custom detection)

3. **Comprehension entry** — post-build understanding entry per SCHEMA.md

4. **README.md** — quick-start, scanner backends table, config model reference, OSS/Premium split explanation, Hermes integration recipe

5. **CHANGELOG.md** — v1.0.0 entry

6. **PyPI publish** — `hatch build` + `hatch publish`, verify `pip install petasos` from PyPI works in clean venv

### Gate criteria

- [ ] Wiki pages pass `wiki-lint.mjs --check`
- [ ] Decision entry follows template from SCHEMA.md
- [ ] README covers: install, all scanner backends, config model, OSS/Premium split, Hermes recipe
- [ ] `pip install petasos` from PyPI succeeds in clean Python 3.11 venv
- [ ] CHANGELOG follows Keep a Changelog format

### Spec traceability

Phase 8 gates, DC-1 (uncoupled from Drawbridge — documented)

---

## PET-13 · Petasos Console — Config & Observability Surface

**Phase:** 9 (Post-core)
**Blocked by:** PET-10 (JWT/premium wiring — Console needs premium_features manifest to render CTAs)
**Blocks:** PET-12 (Wiki/docs should cover Console)
**Spec:** `petasos-console-spec.md`
**Footgun §§:** §2, §3, §14

### Scope

Ship **Petasos Console** as `petasos[console]` pip extra — a lightweight FastAPI + vanilla HTML/JS web application providing:

1. **Config Editor** (OSS) — interactive form generated from `PetasosConfig` field metadata. All sections render; premium fields are visible but disabled without a license, with inline activation CTAs. Session-restart notice on config changes (§3).

2. **Scan Playground** (OSS) — text input + direction toggle + optional session ID. Returns full `PipelineResult`: normalized diff, per-scanner findings, merged findings, anonymized output, latency breakdown. Premium users also see frequency score, escalation tier, profile applied.

3. **Observability Dashboard** (split OSS/Premium):
   - OSS: scan history (last N scans), scanner health (loaded/failed/unavailable, latency)
   - Premium: audit log viewer (filterable by session/severity/type), escalation timeline, frequency heatmap, alert feed, session inspector

### Architecture

- **Backend:** FastAPI (optional dep), in-process alongside Pipeline. Endpoints: `GET/PUT /api/config`, `POST /api/scan`, `GET /api/events` (SSE stream), `GET /api/health`.
- **Frontend:** Single-page vanilla HTML/JS/CSS, no build step, ships as Python package data.
- **Real-time:** SSE for audit/alert streaming. Console hooks `on_audit` and `on_alert` callbacks.
- **Embedding:** Hermes Desktop webview → `http://localhost:{port}/`. Binds `127.0.0.1` only. Port via `PETASOS_CONSOLE_PORT` or constructor arg.

### Design decisions

1. **No React / no build step** — vanilla HTML/JS as package data. `pip install petasos[console]` is self-contained; no node/npm needed.
2. **In-process server, not sidecar** — hooks callbacks directly, no IPC overhead. Consumer calls `serve()` explicitly; Console never auto-starts.
3. **SSE over WebSocket** — one-way event stream, auto-reconnects, proxy-friendly.
4. **Premium visible but disabled** — users discover features organically, activate inline without page reload.
5. **Reference implementation** — consumers with their own UI can ignore Console and consume the same APIs (JSON config, callbacks, `premium_features` manifest).

### Gate criteria

- [ ] `petasos[console]` installs FastAPI + uvicorn as optional deps
- [ ] `petasos.console.serve(pipeline)` starts server on localhost
- [ ] Config editor renders all `PetasosConfig` fields with correct types and constraints
- [ ] Config PUT validates and applies changes (with session-restart notice)
- [ ] Scan playground accepts text and displays full `PipelineResult`
- [ ] SSE stream delivers audit events and alerts in real time
- [ ] Scan history and scanner health panels functional (OSS)
- [ ] Premium sections render disabled with activation CTA
- [ ] Inline activation accepts JWT and unlocks without reload
- [ ] Audit log viewer, alert feed, frequency heatmap functional (Premium)
- [ ] Embeddable in Hermes Desktop webview (localhost binding, theme support)
- [ ] Zero added latency to pipeline scan path

### Spec traceability

`petasos-console-spec.md` — full spec with landscape analysis, architecture diagram, API surface, OSS/Premium boundary table, Hermes Desktop constraint mitigations

---

## Dependency Graph

```
PET-1 (Foundation)
 └─→ PET-2 (Scanner Wrappers — parent)
      ├─→ PET-3 (LlmGuard)         ─┐
      ├─→ PET-4 (LlamaFirewall)     ─┼─→ PET-6 (Pipeline / OSS complete)
      └─→ PET-5 (Presidio)          ─┘         │
                                                ├─→ PET-7 (Frequency + Escalation)
                                                │         │
                                                │         ├─→ PET-8 (Profiles + Guard)  ─┐
                                                │         └─→ PET-9 (Audit + Alerting)  ─┤
                                                │                                        │
                                                └───────────────────────────────────────→ PET-10 (JWT + Hardening)
                                                                                               ├────────────────────────────────→ PET-13 (Console)  ─┐
                                                                                               │                                                     │
                                                                                         PET-11 (Integration + Benchmarks)                           │
                                                                                               │                                                     │
              PET-14 (Red-team review) ─→ PET-15..74 (Remediations)  ──────────────────────────┴─────────────────────────────────────────────────────┘
                                                                                               │
                                                                                         PET-12 (Wiki + Docs + Release)
```

## Parallelism opportunities

- **PET-3, PET-4, PET-5** — fully independent scanner wrappers, three CC squads can work simultaneously
- **PET-8 and PET-9** — independent premium modules (both read frequency/escalation state but don't write to each other), can be parallelized
