# Petasos — Project Spec

> Status: **DRAFT**
> Author: Devin Matthews / Claude
> Date: 2026-05-24
> Plane project: `PET` (UUID `5bff6316-84ea-4103-b9e2-4861ac9c226a`)
> Repo: `vigil-harbor/petasos` (greenfield)
> License: MIT (public security plugin, OSS with Premium tier)

---

## 1. What Petasos Is

Petasos is a pluggable, session-aware content security pipeline for Python AI agents. It composes best-in-class OSS scanners (LLM Guard, LlamaFirewall, Presidio) behind a unified Scanner protocol, adds session-aware orchestration that no OSS tool provides (frequency tracking, escalation tiers, profile-driven tuning, tool call guard), and exposes every configuration surface for frontend binding.

Petasos is **not** a Drawbridge port. It is Drawbridge-*inspired* — same architectural family (session-aware pipeline over scanner backends), different runtime, different dependencies, different threat model decisions, independent release cadence. Drawbridge stays TypeScript + ClawMoat. Petasos stays Python + OSS-composed.

### 1.1 Primary Consumer

Hermes Agent (Nous Research, Python 3.11+). Petasos imports in-process as a Python library. No sidecar, no REST bridge, no subprocess.

### 1.2 What Hermes Already Has

Hermes ships a 7-layer defense model. Petasos complements layers 5–7, does not replace layers 1–4:

| Layer | Hermes provides | Petasos role |
|-------|----------------|--------------|
| 1. User authorization | Allowlists, DM pairing | None — Hermes concern |
| 2. Dangerous command approval | Human-in-the-loop (manual/smart/off) | None — Hermes concern |
| 3. Container isolation | Docker/Singularity/Modal/Daytona/Vercel | None — Hermes concern |
| 4. MCP credential filtering | Safe env-var allowlist | None — Hermes concern |
| 5. Context file scanning | Basic prompt injection in SOUL.md | **Upgrade** — semantic detection via ML models |
| 6. Cross-session isolation | Per-platform, per-user data separation | **Extend** — session-aware frequency tracking |
| 7. Input sanitization | Working dir validation, symlink, SSRF, Tirith | **Extend** — PII anonymization, content redaction, audit trails |

Petasos also covers ground Hermes has **no layer for**: output scanning (LLM response → user), tool call policy guard with frequency-aware escalation, structured compliance audit trails, and agent alignment checking.

---

## 2. Requirements

### 2.1 Functional Requirements

**FR-1: Pluggable scanner backends.** Users configure one or more scanner backends. Each backend implements a Scanner protocol. The pipeline runs all configured scanners and merges findings. Backends ship out of the box:

- `LlmGuardScanner` — wraps LLM Guard's PromptInjection scanner (DeBERTa-v3)
- `LlamaFirewallScanner` — wraps LlamaFirewall's PromptGuard 2 + AlignmentCheck
- `PresidioScanner` — wraps Presidio AnalyzerEngine for PII detection
- `MinimalScanner` — syntactic regex rules only, zero ML deps

Users can enable any combination. Configuration is explicit and serializable (YAML/JSON/dict).

**FR-2: PII detection and anonymization.** Presidio-backed. Detect PII entities in message content, anonymize via position-based redaction with configurable operators (redact, replace, hash, mask). HMAC-SHA256 hashing for audit correlation.

**FR-3: Pipeline orchestration.** Content flows through a fixed pipeline: normalize → pre-filter → scan (N backends) → merge findings → produce result. The pipeline never throws — all errors caught and returned in the result.

**FR-4: Configuration-first design.** Every tunable is exposed as a typed configuration surface: scanner selection, thresholds, PII entity types, rule severity overrides. Config is a Python dataclass / Pydantic model, serializable to JSON for frontend binding.

**FR-5: Input and output scanning.** Scan both inbound (user → agent) and outbound (agent → user/tool) content. Direction is a first-class parameter.

### 2.2 Premium Requirements (session-aware orchestration)

**PR-1: Session-aware frequency tracking.** Per-session suspicion scoring via exponential decay + rolling window counters. Configurable half-life, tier thresholds.

**PR-2: Escalation tiers.** Three tiers with configurable responses: Tier 1 (forced deep scan), Tier 2 (enhanced scrutiny / optional block), Tier 3 (session termination, cannot be disabled).

**PR-3: Profile-driven tuning.** Built-in profiles (general, customer-service, code-generation, research, admin) adjust scanner thresholds, PII sensitivity, and rule suppression per use case. Custom profiles supported.

**PR-4: Tool call policy guard.** Evaluates tool calls before execution against frequency-aware policy. Tool name normalization, tier-aware blocking, parameter content scanning.

**PR-5: Structured audit trails.** Verbosity-gated audit events with structured payloads. Callback-driven — consumer wires to their observability stack. Tamper-evident event ordering.

**PR-6: Alert rules.** Built-in alert rules with rate limiting, cross-session burst detection, critical exemptions. Callback-driven alerting.

### 2.3 Non-Functional Requirements

**NFR-1: Python 3.11+** (matches Hermes).

**NFR-2: Pipeline latency budget.** Syntactic-only path < 5ms. Single ML scanner path < 100ms. Full pipeline (2 ML scanners + PII) < 250ms. All on CPU.

**NFR-3: Configurable fail-mode (default: degraded).** Three modes control what happens when a scanner errors at runtime:

- **`degraded`** (default) — If at least one scanner is still running, content passes through with reduced coverage. If *all* ML scanners fail, content is blocked. The syntactic pre-filter (MinimalScanner, zero deps, pure regex) always runs and cannot fail to load, so "all scanners fail" means "all ML scanners fail" — the regex baseline still catches obvious patterns.
- **`open`** — All scanner failures are non-blocking. Content always passes through. Use for development, testing, or availability-first systems.
- **`closed`** — Any scanner failure blocks content. Use for compliance-regulated environments or PII-sensitive systems where a missed scan is worse than a blocked message.

The decision to default to `degraded` rather than `open` is deliberate: Petasos is a security library — the user installed it because they want security. "Your security silently stops working" is a worse failure mode than "your security is briefly more conservative." But full `closed` is too brittle for a multi-scanner architecture — one transient error in one of three scanners shouldn't block all content when two scanners are still protecting. `degraded` threads the needle. See `decisions/2026-05-24-petasos-fail-mode-degraded-default.md` for the full trade-off analysis.

**NFR-4: Zero required ML deps at install.** Base install (`pip install petasos`) pulls only the pipeline, config, and syntactic rules. Scanner backends are extras: `pip install petasos[llm-guard]`, `petasos[llamafirewall]`, `petasos[presidio]`, `petasos[all]`. This reverses the parked spec's "hard deps" decision — 300MB install for a library most consumers will use selectively is wrong for an OSS adoption play.

**NFR-5: Test coverage.** Security-grade: ≥90% line coverage on pipeline, frequency, guard, audit, alerting. Every scanner wrapper has integration tests against the real backend.

---

## 3. Architecture

### 3.1 Scanner Protocol

The load-bearing abstraction. Every detection backend implements this:

```python
from typing import Protocol

class Scanner(Protocol):
    @property
    def name(self) -> str: ...

    async def scan(self, text: str, *, direction: Direction = "inbound",
                   session_id: str | None = None) -> ScanResult: ...
```

`ScanResult` carries typed findings with source attribution (`scanner_name`, `finding_type`, `severity`, `position`, `confidence`). The pipeline merges results from N scanners, deduplicates overlapping findings, and computes the aggregate severity.

### 3.2 Scanner Backends

| Backend | Wraps | Detects | Install extra |
|---------|-------|---------|--------------|
| `MinimalScanner` | Nothing — pure Python regex | Syntactic injection patterns (17 rules from Drawbridge heritage) | None (ships with base) |
| `LlmGuardScanner` | `llm-guard` PromptInjection, Toxicity, BanTopics, InvisibleText, Secrets | Semantic prompt injection, toxicity, secrets, invisible chars | `petasos[llm-guard]` |
| `LlamaFirewallScanner` | `llamafirewall` PromptGuard 2, AlignmentCheck, CodeShield | Jailbreak, agent goal hijacking, unsafe code generation | `petasos[llamafirewall]` |
| `PresidioScanner` | `presidio-analyzer` + `presidio-anonymizer` | PII entities (50+ types), anonymization | `petasos[presidio]` |

Users compose:

```python
from petasos import Pipeline
from petasos.scanners import LlmGuardScanner, LlamaFirewallScanner, PresidioScanner

pipeline = Pipeline(
    scanners=[
        LlmGuardScanner(threshold=0.85),
        LlamaFirewallScanner(enable_alignment_check=True),
        PresidioScanner(entities=["PERSON", "EMAIL", "PHONE"]),
    ],
)

result = await pipeline.inspect("some user message", session_id="abc")
```

### 3.3 Pipeline Stages

```
Input
  → Normalize (NFKC, zero-width strip, homoglyph map, RTL detection)
  → Syntactic pre-filter (17 regex rules, always runs, deterministic)
  → Fan-out to N configured scanners (concurrent via asyncio.gather)
  → Merge findings (deduplicate overlapping positions, compute aggregate severity)
  → [Premium] Frequency update (findings feed session suspicion score)
  → [Premium] Escalation check (tier evaluation, policy enforcement)
  → Anonymize (if PII findings + anonymization enabled — Presidio AnonymizerEngine)
  → [Premium] Audit emission (verbosity-gated structured events → callback)
  → [Premium] Alert evaluation (rule matching → callback)
  → PipelineResult { safe, findings, sanitized_content, escalation_tier, events, alerts }
```

Free tier runs: normalize → pre-filter → scan → merge → anonymize → result.
Premium tier adds: frequency → escalation → audit → alerting.

### 3.4 Configuration Model

```python
@dataclass
class PetasosConfig:
    # Scanner selection — list of scanner instances or config dicts
    scanners: list[Scanner | dict]

    # Direction
    direction: Direction = "inbound"

    # Fail mode — what happens when a scanner errors
    fail_mode: Literal["open", "closed", "degraded"] = "degraded"

    # Normalization
    normalize_nfkc: bool = True
    strip_zero_width: bool = True
    map_homoglyphs: bool = True
    detect_rtl_override: bool = True

    # PII / Anonymization
    anonymize: bool = True
    pii_entities: list[str] = field(default_factory=lambda: ["DEFAULT"])
    redaction_mode: Literal["redact", "replace", "hash", "mask"] = "redact"
    hash_key: str | None = None  # HMAC key for hash mode

    # Premium features — configured here, activated by license key at runtime.
    # If no valid key, these settings are preserved but the stages are skipped,
    # and result.premium_features reports what would have run.

    # Frequency tracking
    frequency_half_life_seconds: float = 60.0
    tier1_threshold: float = 15.0
    tier2_threshold: float = 30.0
    tier3_threshold: float = 50.0

    # Profiles
    profile: str | ResolvedProfile = "general"

    # Audit
    audit_verbosity: AuditVerbosity = "standard"
    on_audit: Callable[[AuditEvent], None] | None = None

    # Alerting
    on_alert: Callable[[Alert], None] | None = None
```

Every field is serializable to JSON (for frontend config UIs) and overridable at runtime.

---

## 4. OSS / Premium Split

The split follows a principle: **detection is free, session intelligence is paid.**

| Capability | OSS (free) | Premium |
|-----------|-----------|---------|
| Scanner protocol + pluggable backends | ✓ | ✓ |
| Syntactic pre-filter (17 rules) | ✓ | ✓ |
| Input normalization | ✓ | ✓ |
| LLM Guard / LlamaFirewall / Presidio wrappers | ✓ | ✓ |
| PII anonymization | ✓ | ✓ |
| Configuration model (JSON-serializable) | ✓ | ✓ |
| Basic PipelineResult (safe/unsafe + findings) | ✓ | ✓ |
| MinimalScanner (zero-dep fallback) | ✓ | ✓ |
| Session-aware frequency tracking | — | ✓ |
| Escalation tiers | — | ✓ |
| Profile-driven tuning | — | ✓ |
| Tool call policy guard | — | ✓ |
| Structured audit trails | — | ✓ |
| Alert rules + rate limiting | — | ✓ |
| Cross-session burst detection | — | ✓ |

The OSS tier is a genuinely useful security pipeline — not a demo. A developer can `pip install petasos[llm-guard,presidio]`, configure two scanners, and get semantic injection detection + PII anonymization out of the box. The premium tier is what teams running agents in production need: "is this session becoming adversarial over time, and what's the compliance trail?"

### 4.1 Enforcement Mechanism

**Principle: hot-unlock.** Pay → get key → features activate immediately. No pipeline rebuild, no restart, no re-login.

Premium features are checked at *execution time*, not construction time. The pipeline always contains the premium code paths (MIT source is visible). When a premium stage would execute (frequency update, escalation check, audit emission, alert evaluation), the pipeline checks the current license state. If valid, the stage runs. If not, the stage is skipped and the result includes a `premium_features` manifest:

```python
result.premium_features = [
    {"feature": "frequency_tracking", "status": "locked"},
    {"feature": "escalation_tiers", "status": "locked"},
    {"feature": "audit_trail", "status": "locked"},
    # ... frontend reads this to render premium badges / upgrade CTAs
]
```

A frontend hooks directly into this to show "Premium" badges on locked features and route users to the payment flow. When the key clears, the very next `pipeline.inspect()` call runs the premium stages — no reconstruction.

**Key mechanism:**

```
User → vigilharbor.com/petasos → creates account → pays → receives signed JWT
                                                                ↓
Library ← petasos.activate(key) or PETASOS_LICENSE_KEY env var
                                                                ↓
Pipeline → validates JWT signature locally (public key in package)
         → no network required at runtime
         → JWT encodes: tier, expiry, customer_id
         → premium stages activate on next inspect() call
```

The JWT is verified locally — no phone-home required for the library to work. The web service (vigilharbor.com/petasos) owns the user account database: account creation, payment processing, key generation, retention flows ("Thanks for flying with Petasos, here's what you can do now..."), usage dashboards. The library is stateless — it validates a signed token and runs the code.

**Why JWT + local validation:**
- Instant gratification — no network round-trip at runtime
- Works offline / in air-gapped environments after initial key retrieval
- User account database lives on the web side where the business wants it (retention, analytics, upgrade prompts) without coupling the library to a backend service
- Key rotation via expiry + refresh flow, not revocation lists

**Roadmap (out of scope for v1, noted for design consideration):**
- Optional phone-home for usage analytics and feature telemetry (opt-in)
- In-app upgrade flow (deep link from `premium_features` manifest → payment page → callback with key)
- Team/org license keys with seat management
- Trial keys with time-limited premium access

---

## 5. Phased Build Plan

Each phase has gate criteria that must pass before the next phase starts.

### Phase 1: Foundation — Scanner Protocol + MinimalScanner

Build the core abstractions: `Scanner` protocol, `ScanResult`, `ScanFinding`, `Direction`, `PipelineResult`. Implement `MinimalScanner` with the 17 syntactic rules ported from Drawbridge. Implement input normalization (NFKC, zero-width, homoglyph, RTL). Set up repo: `pyproject.toml` (Hatch), `ruff`, `mypy`, `pytest`, CI.

**Gate:**
- [ ] `MinimalScanner` detects all 17 rule categories against a fixed corpus
- [ ] Normalization strips zero-width, maps confusable homoglyphs, detects RTL
- [ ] `mypy --strict` clean, `ruff` clean
- [ ] ≥50 tests passing

### Phase 2: OSS Scanner Wrappers

Implement `LlmGuardScanner`, `LlamaFirewallScanner`, `PresidioScanner` as extras. Each wrapper: installs cleanly, loads the backend lazily, maps backend output to `ScanResult`, handles backend failures gracefully (fail-open).

**Gate:**
- [ ] Each wrapper passes integration tests against real backend (not mocked)
- [ ] `pip install petasos[all]` in a clean Python 3.11 venv succeeds
- [ ] Each scanner independently produces correct findings for a 20-message test corpus
- [ ] Fail-open verified: backend import error → scanner skipped, pipeline continues

### Phase 3: Pipeline Orchestration (OSS tier complete)

Implement `Pipeline` class: normalize → pre-filter → fan-out scan → merge → anonymize → result. Concurrent scanner execution via `asyncio.gather`. Finding deduplication for overlapping positions. Presidio-backed anonymization with configurable operators.

**Gate:**
- [ ] Pipeline runs end-to-end with 1, 2, or 3 scanners configured
- [ ] Concurrent execution verified (scanners don't block each other)
- [ ] Anonymization produces correct redaction with HMAC correlation
- [ ] Pipeline never throws — all error paths return valid PipelineResult
- [ ] Latency budget met: syntactic < 5ms, single ML < 100ms, full < 250ms on CPU
- [ ] ≥120 tests passing
- [ ] **OSS tier is shippable** — tag `v0.1.0-alpha.1`

### Phase 4: Frequency Tracking + Escalation (Premium)

Port FrequencyTracker from Drawbridge: exponential decay scoring, rolling window counters, LRU session eviction. Implement 3-tier escalation with configurable thresholds. Wire into pipeline post-scan.

**Gate:**
- [ ] Frequency scores match Drawbridge reference output for a fixed input sequence (cross-runtime conformance)
- [ ] Tier 3 cannot be disabled (hardcoded floor)
- [ ] Session eviction under memory pressure verified
- [ ] ≥40 frequency + escalation tests

### Phase 5: Profiles + Tool Call Guard (Premium)

Implement profile system: 5 built-in profiles loaded from JSON config, custom profile support via dict/dataclass. Implement ToolCallGuard: tool name normalization, tier-aware blocking, parameter content scanning via pipeline.

**Gate:**
- [ ] All 5 built-in profiles load and adjust scanner thresholds correctly
- [ ] Custom profile overrides work
- [ ] ToolCallGuard blocks at tier2/tier3, escalates warnings at tier1
- [ ] Parameter scanning routes through pipeline correctly
- [ ] ≥50 profile + guard tests

### Phase 6: Audit + Alerting (Premium)

Implement AuditEmitter: verbosity-gated structured events, callback-driven emission. Implement AlertManager: 5 built-in rules, rate limiting, cross-session burst detection, critical exemption. Wire into pipeline.

**Gate:**
- [ ] Audit events emitted at correct verbosity levels
- [ ] Alert rules fire correctly against known trigger sequences
- [ ] Rate limiting prevents alert storms
- [ ] Cross-session burst detection works across multiple session IDs
- [ ] ≥50 audit + alerting tests

### Phase 7: Integration + Hardening

Hermes integration smoke test. End-to-end pipeline tests with all premium features enabled. Security hardening pass: defensive copies, frozen configs, mutation prevention. Performance benchmarking.

**Gate:**
- [ ] `import petasos` works inside a Hermes-imported module
- [ ] No dep conflicts with Hermes's dependency graph (spaCy, transformers versions)
- [ ] Full test suite: ≥300 tests, ≥90% line coverage on core modules
- [ ] Security hardening checklist (from Drawbridge's 3-pass model) applied
- [ ] Performance benchmarks documented
- [ ] **Full package shippable** — tag `v1.0.0`

### Phase 8: Wiki + Docs + Release

Wiki pages (`projects/petasos/` directory), decision entry, Hermes integration recipe, README, CHANGELOG, PyPI publish.

**Gate:**
- [ ] Wiki: architecture.md, state.md, filemap.md created per SCHEMA.md
- [ ] Decision entry: `decisions/2026-05-24-petasos-oss-compose.md`
- [ ] README documents all scanner backends, config model, OSS/Premium split
- [ ] PyPI `petasos` package installable
- [ ] Comprehension entry written

---

## 6. Decisions Carried Forward

**DC-1: Petasos is uncoupled from Drawbridge.** Own repo, own ticket prefix (PET), own release cadence, own threat model. No shared rule package, no cross-runtime conformance suite, no coordinated releases. Drawbridge stays TypeScript + ClawMoat.

**DC-2: Pluggable scanner backends via extras, not hard deps.** Base install is lightweight. Each ML backend is an optional extra. Reverses the parked spec's "hard deps for simplicity" decision — the OSS adoption story requires a small base footprint.

**DC-3: LLM Guard and LlamaFirewall are both first-class.** Users toggle either or both. The Scanner protocol abstracts the backend; the pipeline merges findings from N scanners. No single-backend lock-in.

**DC-4: Detection is free, session intelligence is paid.** The OSS tier is a complete security pipeline (scan, detect, anonymize). The premium tier adds session-aware orchestration (frequency, escalation, profiles, guard, audit, alerting). Open-core model with license key gating.

**DC-5: Configuration-first.** Every tunable is a typed, serializable config field. Frontend binding is a first-class use case, not an afterthought.

**DC-6: Hermes integration is in-process Python import.** No sidecar, no REST, no subprocess. Petasos is a library, not a service.

**DC-7: Default fail-mode is `degraded`, not `open`.** Petasos is a security library — silent total failure is a worse outcome than conservative blocking. `degraded` means: if at least one scanner is running, content flows; if all ML scanners are down, content blocks; the syntactic pre-filter (zero deps) always runs as a structural backstop. Configurable to `open` or `closed` per deployment. Drawbridge chose fail-open because ClawMoat was an optional peer dep and the alternative was "pipeline doesn't work at all." Petasos's multi-scanner architecture makes `degraded` the better default — partial coverage is still coverage; zero coverage is a security incident.

**DC-8: Premium enforcement is hot-unlock via signed JWT, checked at execution time.** No pipeline reconstruction on key activation. The pipeline always contains premium code paths; license state is checked when each premium stage would execute. User account database lives on the web service side (vigilharbor.com/petasos), not in the library. The library validates a signed token locally — no network required at runtime.

---

## 7. Done When

- [ ] `pip install petasos` works in a clean Python 3.11+ environment (< 5MB base)
- [ ] `pip install petasos[all]` brings all scanner backends (~300MB with models)
- [ ] Pipeline runs with 0, 1, 2, or 3+ scanner backends configured
- [ ] Scanner protocol documented, any custom Scanner plugs in
- [ ] OSS tier: syntactic + ML detection + PII anonymization, no license key needed
- [ ] Premium tier: frequency + escalation + profiles + guard + audit + alerting, license-gated
- [ ] ≥300 tests, ≥90% coverage on pipeline/frequency/guard/audit/alerting
- [ ] Hermes smoke test passes in CI
- [ ] Latency budgets met on CPU
- [ ] Wiki pages + decision entry + comprehension entry filed
- [ ] PyPI published, README complete
- [ ] Drawbridge has no Python obligation; Petasos has no TS obligation

---

## 8. Out of Scope

- **Drawbridge coupling artifacts** — no shared rule package, no cross-runtime conformance, no coordinated versioning with Drawbridge.
- **OpenClaw plugin** — Hermes isn't OpenClaw. If needed later, it's a separate package.
- **Web UI / dashboard** — consumer concern. Petasos exposes config and callbacks; the UI is the consumer's job.
- **Streaming inputs** — full-buffer only for v1. Streaming is future research.
- **Browser-tool sanitization (DBR-6)** — Drawbridge scope, not Petasos.
- **Model hosting / mirroring** — consumers pull models from HuggingFace. Document mirroring options for air-gapped deployments but don't ship infrastructure.
- **Rust port (Talaria)** — speculative, not on roadmap.
- **NeMo Guardrails / Guardrails AI integration** — evaluated and rejected. NeMo's Colang DSL conflicts with Petasos's primitives model. Guardrails AI is the wrong abstraction level.
- **Microsoft Agent Governance Toolkit integration** — promising for compliance mapping but too new (April 2026) and too opinionated about identity/mesh. Monitor for v2 consideration.

---

## 9. OSS Ecosystem Survey (May 2026)

Preserved for reference. This survey informed the architecture decisions above.

| Tool | Version | License | What it does | Petasos verdict |
|------|---------|---------|-------------|-----------------|
| **Microsoft Presidio** | 2.2.362 (Mar 2026) | MIT | PII detection + anonymization. NER + regex + LLM recognizers. Industry standard. | **Use** — wrap as `PresidioScanner` |
| **LLM Guard** | 0.3.16 | MIT | 15 input + 20 output scanners. DeBERTa-v3 PromptInjection. Toxicity, secrets, invisible text, banned topics. | **Use** — wrap as `LlmGuardScanner` |
| **LlamaFirewall** | Latest (Meta) | MIT | PromptGuard 2 (jailbreak), AlignmentCheck (CoT auditor), CodeShield (static analysis). Production at Meta. | **Use** — wrap as `LlamaFirewallScanner` |
| **MS Agent Governance Toolkit** | v0.x (Apr 2026) | MIT | Policy enforcement, zero-trust identity, OWASP 10/10, compliance mapping. Sub-ms latency. | **Monitor** — too new, too opinionated for v1. Potential v2 integration for compliance layer. |
| **OpenAI Guardrails Python** | Current | OpenAI | Tool-call injection detection, LLM-as-judge. | **Skip** — API-bound (requires OpenAI calls), conflicts with local-first principle |
| **NeMo Guardrails** | 0.20.0 (Jan 2026) | Apache 2.0 | Colang DSL for conversational guardrails. Heavy framework. | **Skip** — DSL conflicts with primitives model |
| **Aegis** | Mar 2026 | MIT | Auto-instrument approach, Merkle audit chain. | **Skip** — too new, overlaps LLM Guard, unproven community |
| **Guardrails AI** | Current | Apache 2.0 | Validator hub, heavyweight framework. | **Skip** — wrong abstraction level |
| **Pytector** | Current | MIT | DeBERTa/DistilBERT prompt injection. | **Skip** — subset of what LLM Guard already does |
| **Tirith** | Current | MIT | Terminal/shell security. Homographs, pipe-to-shell, ANSI injection. | **Skip** — already in Hermes, different concern (terminal, not content) |

---

## Appendix A — Why "Petasos"

The petasos is the broad-brimmed traveler's hat Hermes wears — winged, boundary-crossing. Petasos the library travels alongside Hermes the agent, carrying protective discipline across the content boundary. Future names if the family grows: Talaria (winged sandals — speculative Rust port), Caduceus (staff — speculative observability surface).
