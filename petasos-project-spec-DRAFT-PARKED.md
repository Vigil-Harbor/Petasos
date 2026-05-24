# Petasos — Project Launch Spec (PARKED DRAFT)

> Status: **PARKED** — preserved research and design intent for a future Petasos project
> Author: Devin Matthews / Claude
> Date: 2026-05-24
> Tickets: TBD when project spins up (likely under a `PET-?` Plane project, not DBR)

---

## Parking Note (2026-05-24)

This document was drafted during Drawbridge v1.4 planning as "the Python port
of Drawbridge with shared rule package and converged semantic model." After
review, that coupling was judged to be more architectural cost than value —
the cross-runtime conformance suite, shared rule package, model pin
coordination, and asymmetric PII detection were collectively buying a "one
threat model, two runtimes" story that was already partial (PII was divergent)
and ongoing maintenance was heavy.

**Decision:** Petasos is uncoupled from Drawbridge entirely. It becomes its own
project — own repo, own ticket prefix, own release cadence, own threat model
decisions. Petasos is Drawbridge-*inspired* (session-aware orchestration over
best-in-class OSS components: Microsoft Presidio for PII, ProtectAI's LLM Guard
for semantic prompt injection), but not Drawbridge-coupled. Drawbridge stays
TypeScript+ClawMoat with no Python obligation; Petasos stays Python+OSS-composed
with no TS obligation.

**What this draft preserves** (and what's still useful when the Petasos project
spins up):

- The OSS ecosystem survey (LLM Guard, Presidio, NeMo Guardrails, Vigil-LLM,
  Rebuff, Guardrails AI — what each does in 2026 and which ones are
  production-grade today)
- The build-vs-buy mapping (custom code only for what's genuinely unique to
  Drawbridge's threat model: frequency tracker, audit, alert, guard, profiles,
  pipeline orchestration; OSS for PII and semantic detection)
- The architectural argument for hard-required deps on Presidio + LLM Guard
- The Hermes integration shape (in-process Python library import)
- The Petasos directory layout, public API surface, and phased CC instruction set

**What's now stale and should be ignored when Petasos spins up:**

- Anything mentioning "Drawbridge v1.4" or "v1.5" — those are Drawbridge
  versions, not Petasos versions. Petasos starts at its own 1.0.0.
- Anything about a shared `@vigil-harbor/drawbridge-rules` package and
  cross-runtime conformance suite — these were the coupling artifacts; Petasos
  ships its own rule set inline.
- Anything about the TS-side `OnnxScanner` work being a Petasos prerequisite —
  that's a Drawbridge improvement that can ship (or not) on Drawbridge's own
  schedule.
- The model pin convention shared across artifacts — Petasos pins its own model
  through LLM Guard; Drawbridge does whatever Drawbridge does.
- DBR ticket prefix references — Petasos work tracks under its own project.

The Drawbridge-flavored framing below remains because rewriting it standalone
is best done when the Petasos project actually starts. Treat this as a
research artifact, not a current spec.

---

## (Below: original Drawbridge-v1.4 framing, preserved for reference)

# Drawbridge v1.4 — Scanner Abstraction + Model Convergence + Petasos Python Port

> Spec for the public security plugin's first cross-runtime release
> Status: PARKED (see Parking Note above)
> Author: Devin Matthews / Claude
> Date: 2026-05-24 (revised after OSS-ecosystem survey)
> Tickets: DBR-? (Scanner abstraction), DBR-? (ONNX semantic backend), DBR-? (Petasos repo launch). All to be filed under the DBR Plane project. DBR-6 (browser sanitization, now v1.5) blocked on this.
> Related: [drawbridge-v1.4-spec-browser-sanitization.md](drawbridge-v1.4-spec-browser-sanitization.md) (originally drafted as v1.5 while this spec held v1.4; restored to v1.4 after uncoupling)

---

## 1. Release Scope

v1.4 ships four items that together make Drawbridge a cross-runtime security layer with a converged semantic-detection backend:

| # | Item | Category |
|---|------|----------|
| 1 | **Formal `Scanner` interface in Drawbridge core** | Headline — promotes the existing duck-typed ClawMoat injection point into a documented, stable contract |
| 2 | **ONNX semantic scanner backend (`OnnxScanner`)** | New TS-side backend wrapping ProtectAI's `deberta-v3-base-injection-onnx` model via Transformers.js — converges TS and Python on a shared semantic model |
| 3 | **Portable rule format (`@vigil-harbor/drawbridge-rules`)** | New shared package — the 17 syntactic rules + profile defaults + model version pin extracted to JSON, consumed by both implementations |
| 4 | **Petasos — Python port with targeted OSS reuse** | New repo (`vigil-harbor/petasos`), PyPI package. Hard deps on Presidio (PII) and LLM Guard (semantic scanner over the same DeBERTa model). Custom for the deterministic core (frequency tracker, audit, alert, guard, profiles, pipeline orchestration). |

Headline framing: **Drawbridge stops being Node-only AND stops re-inventing OSS that's already best-in-class.** The earlier draft of v1.4 proposed a full Python port from scratch — that was the wrong instinct. The Python LLM-security ecosystem in 2026 has mature components for the pieces we'd otherwise rebuild: Microsoft Presidio for PII, ProtectAI's LLM Guard for semantic prompt injection (built on the same DeBERTa-v3 model we can wrap on the Node side via ONNX). We use them. The custom code stays focused on what's unique to Drawbridge: session-aware frequency tracking, escalation tiers, audit verbosity, alert rules, the tool-call guard, profile-driven tuning, the pipeline that wires it all together.

The convergence move is the most important architectural choice here. Both runtimes wrap **the same model** (`protectai/deberta-v3-base-injection-onnx`) for semantic detection — Node via Transformers.js / `onnxruntime-node`, Python via LLM Guard's native HuggingFace usage. The model is pinned in the shared rule package; bumping it is a coordinated cross-runtime release event. Conformance between TS and Python becomes much cleaner because the underlying detector is byte-identical, not just behaviorally similar.

DBR-6 (browser-tool sanitization) is the original motivating ticket; that work is now blocked on v1.4 and rescheduled as v1.5.

---

## 2. Problem Statement

The Gavin web search sanitization ticket (DBR-6) surfaced the runtime mismatch — Hermes is Python 3.11+, Drawbridge is TypeScript/Node, ClawMoat is npm — and the initial pivot was "port Drawbridge to Python." A subsequent ecosystem survey changed the answer.

**What the Python LLM-security ecosystem actually offers (May 2026):**

- **Microsoft Presidio** (MIT, latest March 2026) — industry-standard PII detection and anonymization. Regex + NER + LLM-based recognizers, customizable, ships an `AnonymizerEngine` that already does position-based redaction with overlap merging. Years ahead of anything we'd rebuild.
- **LLM Guard** (ProtectAI, MIT, v0.3.16, Python 3.10+) — 15 input + 20 output scanners. The `PromptInjection` scanner is backed by ProtectAI's fine-tuned DeBERTa-v3 model. `Anonymize`/`Deanonymize` wrap Presidio. Also covers secrets, toxicity, jailbreak, invisible text, malicious URLs.
- **ProtectAI's `deberta-v3-base-injection-onnx`** — the same DeBERTa model exported to ONNX, available directly on HuggingFace. Runs in Node via Transformers.js or `onnxruntime-node`. 184M params; INT8-quantized variant brings deployment payload to ~180MB.
- **NeMo Guardrails, Guardrails AI, Vigil-LLM, Rebuff** — surveyed and rejected. NeMo and Guardrails AI are heavier frameworks with strong opinions about conversational flow that conflict with Drawbridge's primitives model. Vigil-LLM is self-marked alpha. Rebuff is explicitly "not recommended for production today" per its own maintainer documentation.

**What this changes:**

1. **We do not write a Python PII detector.** Presidio is the right tool. Rebuilding it would be busywork and produce a worse result.
2. **We do not write a Python semantic scanner.** LLM Guard's `PromptInjection` wraps a model that's specifically fine-tuned for the task. It's MIT and active.
3. **We do not maintain two separate models for semantic detection.** Node uses the ONNX export of the same DeBERTa model that LLM Guard uses natively in Python. This is the convergence move — divergence in semantic detection becomes structurally impossible because the detector weights are identical.
4. **We do keep custom code for what's actually unique to Drawbridge** — session-aware frequency tracking with exponential decay, escalation tiers, tool-call policy guard, audit verbosity gating, alert rules, profile-driven tuning, the pipeline orchestration that wires it all together. Roughly 2000 lines instead of 8000 across two runtimes.

The result is a smaller, more maintainable codebase that inherits security improvements from the active OSS communities maintaining Presidio and LLM Guard, while keeping the Drawbridge-specific value-add (session awareness, audit/alert discipline, the guard) as the layer that actually makes Drawbridge worth installing.

---

## 3. Architecture

### 3.1 Four Components, One Contract

```
┌─────────────────────────────────────────────────────────────────┐
│  @vigil-harbor/drawbridge-rules  (new shared package)           │
│  - 17 syntactic rules as JSON (regex + ruleId + severity)       │
│  - 5 built-in profile configs as JSON                           │
│  - Pinned model reference (e.g. protectai/deberta-v3-base-      │
│    injection-onnx@2.1.0)                                        │
│  - Conformance test corpus                                      │
└────────────────────────┬────────────────────────────────────────┘
                         │ consumed by
        ┌────────────────┼─────────────────────┐
        ▼                                       ▼
┌────────────────────┐                ┌──────────────────────────┐
│  Drawbridge (TS)   │                │  Petasos (Python)        │
│  v1.4              │                │  v1.0 (first release)    │
│                    │                │                          │
│  Custom:           │                │  Custom (port):          │
│  - Pipeline        │                │  - Pipeline              │
│  - Frequency       │                │  - Frequency             │
│  - Audit / Alert   │                │  - Audit / Alert         │
│  - Guard           │                │  - Guard                 │
│  - Profiles        │                │  - Profiles              │
│  - Syntactic       │                │  - Syntactic             │
│    pre-filter      │                │    pre-filter            │
│                    │                │                          │
│  Scanner backends: │                │  Scanner backends:       │
│  - MinimalScanner  │                │  - MinimalScanner        │
│  - OnnxScanner ◄───┼─ same model ───┼─► LlmGuardScanner        │
│    (Transformers.  │                │    (LLM Guard's          │
│    js wrapper)     │                │    PromptInjection)      │
│  - ClawMoatScanner │                │                          │
│    (legacy / opt)  │                │  Sanitization / PII:     │
│                    │                │  - PresidioSanitizer     │
│  Sanitization:     │                │    (wraps Presidio       │
│  - sanitizeContent │                │    AnonymizerEngine)     │
│    (custom)        │                │                          │
└────────────────────┘                └──────────────────────────┘
       npm                                       PyPI
                                              (deps: presidio,
                                               llm-guard)
```

The **shared rule package** is the single source of truth for syntactic detection and profile configuration. The **shared model pin** is the single source of truth for semantic detection — both runtimes load the same DeBERTa weights, just via different inference stacks. The **Scanner interface** is the contract behind which alternative backends plug in.

### 3.2 The Scanner Interface

v1.3 has `DrawbridgeScanner` (`src/scanner/index.ts:62`) which accepts a `ClawMoatEngine` via constructor injection — already duck-typed as `{ scan(text: string): ClawMoatScanResult }` (`src/scanner/index.ts:53-55`). v1.4 formalizes this:

```ts
// src/scanner/types.ts (new file)

export interface Scanner {
  /**
   * Inspect a string for prompt injection and PII patterns.
   * Synchronous or async (consumer chooses; pipeline awaits if needed).
   */
  scan(text: string, opts?: ScanOptions): Promise<ScanResult> | ScanResult;
}

export interface ScanOptions {
  sessionId?: string;
  direction?: "inbound" | "outbound";
}

export interface ScanResult {
  findings: ScanFinding[];
  highestSeverity: "none" | "low" | "medium" | "high" | "critical";
  /** Which backend produced this result (for audit correlation) */
  backend: string;
}

export interface ScanFinding {
  ruleId: string;
  severity: "low" | "medium" | "high" | "critical";
  position: { start: number; end: number };
  matchedText?: string;
  source: "syntactic" | "semantic" | "schema" | "pii";
  /** Backend-specific confidence score (semantic backends only) */
  score?: number;
}
```

Three backends ship in v1.4:

| Backend | Class | Backend dep | What it detects |
|---------|-------|-------------|-----------------|
| `MinimalScanner` | `src/scanner/minimal.ts` (new) | None — zero-dep | Syntactic rules from the rule package only |
| `OnnxScanner` | `src/scanner/onnx.ts` (new, headline) | `@huggingface/transformers` + model from HF | DeBERTa-v3 semantic prompt injection |
| `ClawMoatScanner` | existing `DrawbridgeScanner` widened | `clawmoat` (peer dep) | Legacy ClawMoat detection — retained for backward compat |

Petasos defines an equivalent Python `Scanner` Protocol with the same semantics. The three backends on the Python side:

| Backend | Module | Backend dep | What it detects |
|---------|--------|-------------|-----------------|
| `MinimalScanner` | `petasos.scanner.minimal` | None — pure Python | Syntactic rules from the rule package only |
| `LlmGuardScanner` | `petasos.scanner.llm_guard` | `llm-guard` | DeBERTa-v3 semantic prompt injection (LLM Guard's `PromptInjection` scanner) |
| `PresidioScanner` | `petasos.scanner.presidio` | `presidio-analyzer` | PII detection (LLM Guard wraps this too, but Petasos uses Presidio directly for finer control) |

Because the underlying DeBERTa model weights are identical between `OnnxScanner` and `LlmGuardScanner`, **semantic findings converge byte-for-byte** modulo tokenizer differences (which are also identical — same DeBERTa-v3 tokenizer used on both sides). The conformance test suite can be strict on semantic detection, not just syntactic.

### 3.3 The Portable Rule Format

The shared rule package (`drawbridge-rules`) bundles:

```json
{
  "version": "1.0.0",
  "rules": [
    {
      "ruleId": "drawbridge.syntactic.injection.ignore-previous",
      "category": "injection",
      "pattern": "ignore previous instructions",
      "flags": "i",
      "severity": "high",
      "description": "Classic prompt injection — instructs the model to disregard prior context"
    }
    // ... 16 more
  ],
  "profiles": {
    "general": { /* full ResolvedProfile JSON */ },
    "customer-service": { /* ... */ },
    "code-generation": { /* ... */ },
    "research": { /* ... */ },
    "admin": { /* ... */ }
  },
  "model": {
    "id": "protectai/deberta-v3-base-injection-onnx",
    "revision": "main",
    "quantization": "int8",
    "minVersion": "2.0.0"
  }
}
```

The `model` block is consumed by `OnnxScanner` (TS) and validated against the LLM Guard version (Python). When the rule package is bumped to point at a new model revision, both runtimes coordinate the upgrade.

JS and Python regex engines are compatible for the rule subset shipped (alternation, anchors, character classes, case-insensitive / multiline flags). A pattern linter in the rule package validates regex compatibility at publish time.

Published to both npm (`@vigil-harbor/drawbridge-rules`) and PyPI (`drawbridge-rules`). Both implementations pin a version range.

### 3.4 Petasos Pipeline — Custom Core + OSS Backends

Petasos implements all 10 pipeline stages from the v1.3 Drawbridge architecture, but most stages thin-wrap OSS rather than reimplementing:

| # | TS Module | Petasos Approach | Notes |
|---|-----------|------------------|-------|
| 1 | Trust check | **Custom port** — `petasos.pipeline.trust` | ~30 LoC, no equivalent OSS |
| 2 | Stringify | **Custom port** — `petasos.lib.safe_stringify` | Python `json.dumps` with circular detection |
| 3 | Syntactic pre-filter | **Custom port** — `petasos.validation.prefilter` | Consumes shared rule JSON. Pure regex, deterministic, ~100 LoC |
| 4 | Frequency update | **Custom port** — `petasos.frequency.tracker` | Unique to Drawbridge — exp decay + rolling window + LRU eviction. ~400 LoC. |
| 5 | Two-pass gate | **Custom port** — `petasos.pipeline.gate` | Direct port |
| 6 | Schema validation | **OSS** — Pydantic | Use Pydantic for MCP tool output validation |
| 7 | Scanner (semantic) | **OSS** — `llm-guard` `PromptInjection` | Wrapped behind Scanner Protocol as `LlmGuardScanner` |
| 7a | Scanner (PII) | **OSS** — `presidio-analyzer` | Wrapped behind PIIDetector interface (new — see §3.5) |
| 8 | Frequency update (post-scan) | Same module as step 4 | Reuse |
| 9 | Sanitize | **OSS** — Presidio `AnonymizerEngine` | Position-based redaction with overlap merging. HMAC custom operator. |
| 10 | Audit + Alert | **Custom port** — `petasos.audit`, `petasos.alerting` | Direct port — unique to Drawbridge |

Plus v1.3 additions:

| | | | |
|---|---|---|---|
| - | `ToolCallGuard` | **Custom port** — `petasos.guard.ToolCallGuard` | Direct port — unique to Drawbridge |
| - | Profiles | **Custom port** — `petasos.profiles` | Loaded from shared rule JSON, ~80 LoC |

**Custom code in Petasos:** approximately 2000 LoC across frequency, audit, alert, guard, profiles, pipeline orchestration, the rule loader, and the syntactic pre-filter. **OSS code wrapped:** Presidio (entire detection engine + anonymizer), LLM Guard (semantic scanner + model loading + tokenization). The OSS pieces are an order of magnitude more code than what we're writing — and we're not maintaining any of it.

### 3.5 PII Detector Interface (new)

The TS Drawbridge today bundles PII detection inside ClawMoat. The OSS Python world treats PII as a separate concern (Presidio is dedicated to it; LLM Guard wraps it). To keep the Petasos API clean and let consumers swap PII backends, v1.4 adds a `PIIDetector` interface alongside `Scanner`:

```python
# petasos/types.py

class PIIDetector(Protocol):
    def detect(self, text: str, language: str = "en") -> list[PIIFinding]: ...
    def anonymize(self, text: str, findings: list[PIIFinding]) -> str: ...
```

On the TS side, the same separation is added (`src/pii/types.ts`), with the ClawMoat-bundled PII surfaced as a `ClawMoatPIIDetector` implementation and a future `PresidioPIIDetector` (via Presidio's REST API, since there's no Node-native Presidio port) deferred to v1.5+.

For v1.4, Drawbridge TS does not gain a Presidio integration — that's deferred. The TS pipeline continues to use ClawMoat's bundled PII detection. The PIIDetector interface is added as a forward-compatible seam.

### 3.6 Hermes Integration Shape

Petasos is imported in-process by Gavin / any Hermes consumer. Two-line setup:

```python
# Inside Hermes / Gavin

from petasos import Pipeline, ToolCallGuard
from petasos.profiles import load_profile
from petasos.scanner import LlmGuardScanner
from petasos.pii import PresidioPIIDetector

pipeline = Pipeline(
    profile=load_profile("general"),
    scanner=LlmGuardScanner(),       # Wraps LLM Guard's PromptInjection
    pii_detector=PresidioPIIDetector(),  # Wraps Presidio AnalyzerEngine
)
guard = ToolCallGuard(pipeline=pipeline, tracker=pipeline.tracker)

# Usage is identical to Drawbridge TS
result = pipeline.inspect(content=user_msg, session_id=session_id, source="user_message")
if not result.safe:
    ...
```

Hermes integration recipe lives in the wiki (`tools/hermes-agent/integrations/petasos.md`), not in Petasos itself. Keeps Petasos consumer-agnostic.

---

## 4. TypeScript-Side Changes

Three substantive changes plus one new headline backend.

### 4.1 Formalize `Scanner` Interface

New file: `src/scanner/types.ts` with the interfaces from §3.2. Export from `src/index.ts`. `DrawbridgeScanner` (existing) gets renamed to `ClawMoatScanner` and gains an `implements Scanner` declaration. Compatibility shim: `DrawbridgeScanner` remains exported as a deprecated alias for `ClawMoatScanner` for one minor version.

### 4.2 New `OnnxScanner` Implementation (headline)

New file: `src/scanner/onnx.ts`. Wraps ProtectAI's `deberta-v3-base-injection-onnx` model via Transformers.js (`@huggingface/transformers`).

Key implementation choices:

- **Model load:** lazy, on first `scan()` call. Model cached locally in `~/.drawbridge/models/` after first download.
- **Quantization:** INT8 by default (~180MB on disk vs ~700MB FP32). Configurable to FP32 for highest fidelity.
- **Tokenizer:** the DeBERTa-v3 tokenizer bundled with the model. Same tokenizer as LLM Guard's Python usage → identical tokenization → identical model inputs given identical text.
- **Inference:** synchronous from the consumer's POV via `await`. Per-call latency on CPU: ~30–80ms for typical message lengths (benchmarked against the model card's reference figures; verify in Phase 7).
- **Output:** model returns a probability of injection (0 = clean, 1 = injection). Threshold (default 0.85, configurable) maps to `severity: "high"` finding.
- **Position:** the DeBERTa model is a sequence classifier, not a span detector. It returns one finding for the entire input when injection is detected, with `position: { start: 0, end: text.length }`. Position-aware semantic detection is deferred.

The `OnnxScanner` becomes the recommended default for new TS consumers. Existing consumers on `ClawMoatScanner` continue to work; migration is opt-in.

### 4.3 New `MinimalScanner` Implementation

New file: `src/scanner/minimal.ts`. A zero-dep `Scanner` implementation that runs only the syntactic rules loaded from `@vigil-harbor/drawbridge-rules`. Promotes the v1.3 "ClawMoat-missing → syntactic-only" fallback to a first-class explicit backend. No model download, no deps; useful for low-resource deployments and testing.

### 4.4 Consume `@vigil-harbor/drawbridge-rules`

The `SYNTACTIC_RULES` constant in `src/validation/index.ts:22-46` gets replaced with a `loadRules()` call that imports from the rule package. Existing exported `SYNTACTIC_RULES` constant remains as a compatibility shim. Bundle size impact: negligible (<10 KB JSON).

### 4.5 PIIDetector Seam

New file: `src/pii/types.ts` with the `PIIDetector` interface. A `ClawMoatPIIDetector` adapter exposes ClawMoat's bundled PII as a `PIIDetector` so the pipeline depends on the interface, not on ClawMoat directly. No behavior change for v1.4 TS consumers.

---

## 5. Petasos Repo Skeleton

New repo: `github.com/vigil-harbor/petasos`. PyPI package: `petasos`.

### 5.1 Directory Layout

```
petasos/
├── pyproject.toml          # Hatch build backend
├── README.md
├── CHANGELOG.md
├── LICENSE                 # MIT
├── petasos/
│   ├── __init__.py
│   ├── pipeline.py         # Pipeline class (10-stage orchestration)
│   ├── scanner/
│   │   ├── __init__.py     # Scanner Protocol
│   │   ├── minimal.py      # MinimalScanner (syntactic-only, zero-dep)
│   │   ├── llm_guard.py    # LlmGuardScanner (wraps llm-guard PromptInjection)
│   │   └── README.md
│   ├── pii/
│   │   ├── __init__.py     # PIIDetector Protocol
│   │   └── presidio.py     # PresidioPIIDetector (wraps presidio-analyzer)
│   ├── validation/
│   │   ├── __init__.py
│   │   ├── prefilter.py    # Custom — syntactic rules from JSON
│   │   ├── normalize.py    # Custom — NFKC, zero-width, homoglyph, RTL (stdlib + confusable_homoglyphs)
│   │   └── schema.py       # Pydantic-based MCP validation
│   ├── frequency.py        # Custom — FrequencyTracker
│   ├── sanitize.py         # Wraps Presidio AnonymizerEngine + HMAC operator
│   ├── audit.py            # Custom — AuditEmitter
│   ├── alerting.py         # Custom — AlertManager
│   ├── guard.py            # Custom — ToolCallGuard
│   ├── profiles.py         # Custom — Profile loading from JSON
│   ├── lib/
│   │   ├── safe_stringify.py
│   │   └── sha256.py
│   └── types.py
├── tests/
│   ├── conformance/        # Cross-runtime conformance harness
│   ├── test_*.py           # ~200 unit tests at v1.0 launch
└── docs/
```

### 5.2 Dependencies

**Required at install time** (per the chosen "hard required deps" architecture):

```toml
[project]
dependencies = [
    "drawbridge-rules>=1.0,<2.0",
    "presidio-analyzer>=2.2,<3.0",
    "presidio-anonymizer>=2.2,<3.0",
    "llm-guard>=0.3.16,<0.4",
    "pydantic>=2.5,<3.0",
    "confusable-homoglyphs>=3.3,<4.0",
]
```

Indirect deps pulled in:
- Presidio brings in **spaCy** (~50MB) + English language model (~15MB)
- LLM Guard brings in **HuggingFace transformers** + tokenizers + the DeBERTa model on first use (~180MB INT8 quantized)

**Total install footprint: ~300MB.** Documented in the README; this is a security-critical library and the size is the price of doing semantic detection well. Consumers who need a smaller footprint can construct `Pipeline(scanner=MinimalScanner())` and skip the heavy deps at runtime, though they still get pulled in at `pip install` time.

A separate `petasos-minimal` extras (`pip install petasos[minimal]` removing presidio + llm-guard) is **explicitly deferred** to keep v1.0 simple. Revisit if there's demand.

Python floor: 3.11 (matches Hermes, matches Presidio's stable line).

### 5.3 Public API Surface

`petasos/__init__.py`:

```python
from .pipeline import Pipeline, PipelineResult, PipelineInput
from .scanner import Scanner, ScanResult, ScanFinding, MinimalScanner, LlmGuardScanner
from .pii import PIIDetector, PIIFinding, PresidioPIIDetector
from .frequency import FrequencyTracker, EscalationTier
from .guard import ToolCallGuard, ToolCallInput, ToolCallGuardResult
from .audit import AuditEmitter, AuditVerbosity
from .alerting import AlertManager, AlertRuleId
from .profiles import load_profile, BUILTIN_PROFILES, ResolvedProfile
from .sanitize import Sanitizer  # wraps Presidio's AnonymizerEngine

__version__ = "1.0.0"
```

### 5.4 What Petasos Does NOT Ship

- No OpenClaw plugin (Hermes isn't OpenClaw)
- No alternative semantic scanner beyond `LlmGuardScanner` and `MinimalScanner` (v1.0)
- No browser-tool sanitization (v1.5)
- No web UI / dashboard (consumer concern)
- No production telemetry sink (callback-driven; consumer wires)

---

## 6. Coordination & Release Strategy

### 6.1 Four Repos, One Release

- `clawmoat-drawbridge-sanitizer` (this repo) — TS Drawbridge v1.4. New: Scanner interface, OnnxScanner, MinimalScanner, PIIDetector seam, consumes rule package.
- `drawbridge-rules` (new repo) — Shared rules + profiles + model pin + conformance corpus. Published to npm and PyPI.
- `petasos` (new repo) — Python implementation. Published to PyPI. Hard deps on Presidio + LLM Guard.
- (Implicit: the **DeBERTa model itself** is the fifth artifact. We don't republish it — both runtimes pull it from HuggingFace at the pinned revision.)

Coordinated release flow:

1. Tag `drawbridge-rules@X.Y.Z`; publish to both registries.
2. Tag Drawbridge TS `v1.4.0`; publish to npm. CI verifies the new rule version works.
3. Tag Petasos `v1.0.0`; publish to PyPI. CI verifies the new rule version + the pinned model both work.
4. Run cross-runtime conformance suite against the published quadruple (rules + Drawbridge + Petasos + model).

For v1.4 this is a single coordinated event. Subsequent releases:

- **Drawbridge-only bugfix** (TS code only) → patch release of Drawbridge; no coordination needed.
- **Petasos-only bugfix** → patch release of Petasos; no coordination.
- **Rule package update** → coordinated triple release.
- **Model pin bump** → coordinated triple release + conformance suite re-run with new model.

### 6.2 Versioning

| Repo | Versioning | Notes |
|------|-----------|-------|
| `drawbridge-rules` | SemVer; rule additions are minor, removals/renames are major | Rule deletions break audit log continuity |
| `protectai/deberta-v3-base-injection-onnx` | ProtectAI controls; we pin to a specific revision | Model bumps coordinated cross-runtime |
| Drawbridge TS | SemVer; v1.4.0 for this release | Backward-compatible |
| Petasos | SemVer; v1.0.0 first release | Tracks Drawbridge feature parity |

Compatibility matrix lives in the wiki (`projects/drawbridge/compatibility.md`).

---

## 7. Test Plan

### 7.1 TS Unit Tests (extends existing 460 tests)

| Test | Description |
|------|-------------|
| `Scanner` interface exported | Compile-time check on consumer-style import |
| `ClawMoatScanner` satisfies `Scanner` | Type check |
| `MinimalScanner` runs syntactic rules | Standard injection patterns flagged with correct ruleId |
| `OnnxScanner` loads model | First call downloads model, subsequent calls use cache |
| `OnnxScanner` flags known injection | DeBERTa identifies "ignore previous instructions" → score > threshold |
| `OnnxScanner` passes clean input | Benign messages → score < threshold |
| `OnnxScanner` INT8 quantization | INT8 model loads, INT8 inference produces findings within 5% confidence of FP32 reference |
| `OnnxScanner` latency budget | Median inference < 100ms on CPU for ≤1KB input |
| `DrawbridgePipeline` accepts custom Scanner | Inject any `Scanner`; pipeline runs and emits expected events |
| Rule package loads at startup | PreFilter consumes JSON; rule taxonomy matches `SYNTACTIC_RULE_TAXONOMY` |
| `PIIDetector` interface exists | `ClawMoatPIIDetector` adapter satisfies interface |
| All 460 v1.3 tests pass unchanged | Backward compat |

### 7.2 Rule Package Tests

| Test | Description |
|------|-------------|
| JSON Schema valid | Shipped rules pass schema validation |
| Patterns compile in JS and Python | Every pattern compiles in both engines |
| Patterns produce identical matches | 100-string corpus → identical matches per rule |
| Profiles reference real rule IDs | Profile configs only reference rules in the taxonomy |
| Model pin is reachable | The pinned model exists on HuggingFace at the named revision |
| No JS-only regex features | Pattern linter rejects named captures, lookbehind, etc. |

### 7.3 Petasos Unit Tests (target ~200 at v1.0 launch)

| Module | Target tests | Notes |
|--------|--------------|-------|
| `test_prefilter.py` | 47 | Mirror Drawbridge prefilter coverage |
| `test_normalize.py` | 29 | Mirror normalize coverage |
| `test_schema.py` | 17 | Pydantic-backed |
| `test_scanner_minimal.py` | 10 | Syntactic-only backend |
| `test_scanner_llm_guard.py` | 8 | Wrapper behavior; mock LLM Guard internals where they're slow |
| `test_pii_presidio.py` | 12 | Presidio wrapper behavior |
| `test_frequency.py` | 34 | Mirror Drawbridge frequency coverage |
| `test_sanitize.py` | 20 | Presidio anonymizer + custom HMAC operator |
| `test_profiles.py` | 24 | Profile resolution |
| `test_audit.py` | 25 | Verbosity, event routing |
| `test_alerting.py` | 20 | Rules, rate limiting |
| `test_pipeline.py` | 30 | End-to-end orchestration |
| `test_guard.py` | 25 | ToolCallGuard parity with Drawbridge |

### 7.4 Cross-Runtime Conformance (the load-bearing test)

Lives in the `drawbridge-rules` repo at `conformance/`. Two layers:

**Strict conformance** (byte-for-byte identical output between TS and Python):
- Syntactic pre-filter findings (regex outputs are deterministic)
- Sanitization positions for syntactic findings
- Frequency tracker score after a fixed input sequence
- Profile resolution output
- Audit event shapes and ordering for a fixed input

**Semantic conformance** (model-output equivalence):
- For each input in a 50-message corpus, both `OnnxScanner` (TS) and `LlmGuardScanner` (Python) produce the same injection probability ±0.001 (within float precision)
- Same `safe`/`unsafe` decision at default threshold
- Same finding count

If the semantic conformance threshold drifts (e.g., because Transformers.js handles a tokenizer edge differently than HuggingFace Python), it's catalogued explicitly as an allowed difference with a regression test pinning the divergence.

**PII conformance**:
- TS side uses ClawMoat's bundled PII (different detector than Petasos's Presidio)
- For this layer, we accept divergence and document it as "different PII engines per runtime, by design"
- Conformance assertions: same severity tier, no PII pattern missed on either side that's caught on the other (asymmetric — a v1.5 work item is to converge PII detection)

### 7.5 Hermes Integration Smoke Test

Petasos CI installs `hermes-agent` and verifies `import petasos` works inside a Hermes-imported module. Catches Python version skew, dep conflicts (especially around spaCy + transformers versions, which can be touchy), namespace issues.

### 7.6 Gavin/Hermes Dogfood (14 days)

Same acceptance as the prior draft. Adds:

- Zero ML model load failures (model downloads succeed, cache works, INT8 inference produces valid outputs)
- LLM Guard's `PromptInjection` finding rate is within expected band (calibration spot-check)
- Presidio's PII detection catches expected entities (calibration spot-check)

---

## 8. Documentation Updates

- **Drawbridge `README.md`** — Scanner backends section, document `OnnxScanner` as the new recommended default, link to Petasos
- **Drawbridge `CHANGELOG.md`** — v1.4.0 entry: Scanner interface, OnnxScanner, MinimalScanner, PIIDetector seam, rule package extraction
- **New repo: `drawbridge-rules/README.md`** — rule format, model pin convention, how to add a rule, how to bump the model safely
- **New repo: `petasos/README.md`** — full API reference; explicit notes about dependency footprint (~300MB) and why
- **New wiki page: `projects/drawbridge/compatibility.md`** — version + model matrix
- **New wiki page: `projects/petasos/` directory** — architecture, state, filemap
- **Updated wiki: `tools/hermes-agent/integrations/petasos.md`** — wiring recipe
- **Decision entry: `decisions/2026-05-24-petasos-oss-leverage.md`** — captures the build-vs-buy analysis, why Architecture B + model convergence won, what alternatives were rejected and why

---

## 9. CC Instruction Set

Five repos and a model coordination. Phases with checkpoint gates.

### Phase 1: Rule Package — Extract & Publish

1. Create `drawbridge-rules` repo per §3.3 layout.
2. Extract rules from `src/validation/index.ts:22-46` into `rules.json`.
3. Extract `BUILTIN_PROFILES` into `profiles.json`.
4. Add `model` block pinning `protectai/deberta-v3-base-injection-onnx`.
5. Write JSON Schema + pattern linter.
6. CI: publish to npm + PyPI on tag.
7. Publish `0.1.0-alpha.1`.

**Checkpoint:** Both registries serve the package; both engines load the rules.

### Phase 2: Drawbridge TS — Scanner Interface + MinimalScanner + Rule Package

1. Add `src/scanner/types.ts` (Scanner interface).
2. Rename `DrawbridgeScanner` → `ClawMoatScanner`; keep deprecated alias.
3. Add `src/scanner/minimal.ts`.
4. Refactor `src/validation/index.ts` to load rules from package.
5. Add `src/pii/types.ts` (PIIDetector interface); add `ClawMoatPIIDetector` adapter.
6. Tests per §7.1 (except OnnxScanner).
7. All 460 v1.3 tests still pass.

**Checkpoint:** `npm test`, `typecheck`, `build` clean. Backward compat verified.

### Phase 3: Drawbridge TS — OnnxScanner

1. Add `@huggingface/transformers` as a dependency.
2. Implement `src/scanner/onnx.ts`: model load, caching, inference, threshold→severity mapping.
3. Add INT8 quantization config.
4. Tests per §7.1 for OnnxScanner.
5. Benchmark latency vs. target budget.
6. Update README + CHANGELOG.

**Checkpoint:** OnnxScanner loads the model, runs inference, flags injections within latency budget.

### Phase 4: Petasos — Repo Scaffold

1. Create `petasos` repo per §5.1 layout.
2. `pyproject.toml` with hard deps on Presidio + LLM Guard + drawbridge-rules.
3. Stub all modules with type signatures.
4. CI: lint, typecheck, test, publish to PyPI on tag.

**Checkpoint:** `pip install -e .` works in a fresh Python 3.11 env. ~300MB total install footprint confirmed.

### Phase 5: Petasos — Custom Modules (port from TS)

1. `petasos.lib.safe_stringify`, `petasos.lib.sha256`
2. `petasos.validation.prefilter` — consumes JSON rules
3. `petasos.validation.normalize` — uses `unicodedata` + `confusable_homoglyphs`
4. `petasos.validation.schema` — Pydantic
5. `petasos.frequency` — FrequencyTracker port
6. `petasos.profiles` — JSON profile loader
7. `petasos.audit` — AuditEmitter port
8. `petasos.alerting` — AlertManager port
9. `petasos.guard` — ToolCallGuard port

Unit tests for each per §7.3.

**Checkpoint:** All custom modules pass tests in isolation.

### Phase 6: Petasos — OSS Wrappers

1. `petasos.scanner.minimal` — pure-syntactic Scanner backend
2. `petasos.scanner.llm_guard` — wraps `llm-guard.input_scanners.PromptInjection`
3. `petasos.pii.presidio` — wraps `presidio_analyzer.AnalyzerEngine` and `presidio_anonymizer.AnonymizerEngine`
4. `petasos.sanitize` — uses Presidio's AnonymizerEngine + custom HMAC operator

Wrapper tests per §7.3.

**Checkpoint:** Wrappers produce expected output against fixed test inputs.

### Phase 7: Petasos — Pipeline Orchestration

1. `petasos.pipeline.Pipeline` — 10-stage orchestration matching Drawbridge `inspect()`
2. End-to-end pipeline tests
3. Hermes integration smoke test in CI

**Checkpoint:** Full Petasos test suite green. ≥200 tests. Hermes smoke test passes.

### Phase 8: Cross-Runtime Conformance

1. Create `conformance/` corpus in `drawbridge-rules`.
2. Generate expected outputs from Drawbridge as reference.
3. Wire `node-runner.mjs` and `python-runner.py` into both CIs.
4. Iterate on Petasos and the OnnxScanner side until strict + semantic conformance both pass.
5. Document allowed-differences list (PII conformance is asymmetric — see §7.4).

**Checkpoint:** Both runners pass against the published quadruple.

### Phase 9: Coordinated Release

1. Tag `drawbridge-rules@1.0.0`; publish to both registries.
2. Tag Drawbridge TS `v1.4.0`; publish to npm.
3. Tag Petasos `v1.0.0`; publish to PyPI.
4. Update wiki: compatibility matrix, Petasos project pages, decision entry.
5. Final conformance run against published versions.

### Phase 10: Gavin Dogfood (14 days)

Deploy. Monitor per §7.6 acceptance. Address issues. Unblock DBR-6 (v1.5).

---

## 10. Open Questions (Resolved)

| Question | Resolution |
|----------|-----------|
| Why use OSS at all when v1.3 is custom? | Custom rebuild of PII (Presidio) and semantic scanning (DeBERTa fine-tune) would produce strictly worse results than the OSS we'd be reimplementing. Inheriting OSS maintenance is a strategic win — we focus engineering on what's actually unique to Drawbridge. |
| Why converge on the same DeBERTa model for both runtimes? | The user explicitly chose model convergence. The architectural payoff is enormous: cross-runtime semantic-detection drift becomes structurally impossible. The work cost is one new TS module (`OnnxScanner`) and a model pin in the rule package. |
| Why hard deps instead of optional extras for Presidio + LLM Guard? | The user explicitly chose hard deps for simplicity. Petasos out-of-the-box "just works" without consumers having to read docs about extras syntax. The ~300MB footprint is acceptable for a security-critical library. Revisit if a use case for lighter footprints emerges. |
| What happens to ClawMoat? | Stays as a Scanner backend on TS side (`ClawMoatScanner`). Existing consumers unaffected. New consumers default to `OnnxScanner`. Deprecation timeline: revisit in v1.6 once `OnnxScanner` has dogfood track record. |
| Why no Presidio on TS side in v1.4? | Presidio is Python-only. Bridging to it from Node would mean a sidecar or REST call to a Presidio service. Deferred to v1.5+ — for v1.4, TS keeps ClawMoat's bundled PII; the `PIIDetector` interface is added as the forward-compatible seam. |
| What's the model lifecycle? | ProtectAI controls model releases. We pin a specific revision in the rule package; bumping is a coordinated cross-runtime release. If ProtectAI ever deprecates the model, we hold at the pinned revision and evaluate alternatives. |
| Async API? | Scanner backends can be sync or async (interface accepts both via `Promise<ScanResult> | ScanResult` on TS, `await`-able on Python). `OnnxScanner` is async (model inference). `MinimalScanner` is sync. Pipeline handles both. |
| Tokenization equivalence between Transformers.js and HuggingFace Python? | Both use the DeBERTa-v3 tokenizer (SentencePiece). Verified equivalent for the rule corpus in Phase 8 conformance. If a divergence is found, raise it upstream to the Transformers.js maintainers. |
| What if `protectai/deberta-v3-base-injection-onnx` lacks the ONNX export we need? | The model is already published in ONNX format on HuggingFace; both standard and INT8-quantized exports are available. Verified in spike during the OSS survey. |

---

## 11. Risk Assessment

| Risk | Mitigation |
|------|-----------|
| OSS dep breaks consumer environments (version conflicts) | Pin upper bounds in `pyproject.toml`. Hermes smoke test in CI catches conflicts before release. Document supported environment matrix. |
| Presidio or LLM Guard slows or stops being maintained | Both are MIT — we can fork. LLM Guard is the higher risk (smaller community than Presidio); abstraction behind `Scanner` Protocol means we can swap backends. |
| Model size (~180MB INT8) is too large for some Hermes hosts | First-call download is one-time; INT8 already a 4x reduction from FP32. Mobile / edge deployments use `MinimalScanner` (syntactic-only). Document size in README. |
| ONNX inference on Node is too slow | Median <100ms on CPU per inference (verified in Phase 3). For pathological large inputs, truncate or batch. Pipeline already handles slow scanners (no fixed timeout). |
| Tokenizer divergence between Transformers.js and HuggingFace Python | Both use the same SentencePiece tokenizer from the model card. Phase 8 conformance verifies. If found, document as allowed-difference and pin the divergence in a regression test. |
| Model bump introduces silent detection regressions | Coordinated release: conformance suite runs against new model in both CIs before publish. A model bump that fails conformance halts the release. |
| spaCy / transformers / Presidio dep graph conflicts | Pin minor versions. CI tests against a fresh-env install. Hermes CI integration test exercises real-world overlap. |
| ClawMoat-side PII detection differs from Presidio | Documented as known asymmetry in §7.4. Convergence to Presidio on TS side is v1.5+ work. |
| Maintenance burden: still two implementations | Smaller than the original full-port plan (~2000 LoC custom vs ~8000). Cross-runtime conformance discipline keeps the custom pieces honest. Model and PII detection no longer require parallel implementation effort. |
| Dependency on HuggingFace availability | Model cached locally after first load. Offline operation works post-cache. Document mirroring options for air-gapped deployments. |
| Public scrutiny on bundling OSS into a "security" product | LLM Guard, Presidio, and Transformers.js are all MIT. We attribute properly in README, CHANGELOG, and the LICENSE bundle. We're a security layer that composes best-in-class OSS — that's a feature, not a tell. |

---

## 12. Out of Scope (v1.4)

- **DBR-6 browser-tool sanitization** → v1.5
- **Presidio integration on TS side** → v1.5+ (requires sidecar or REST bridge to Python)
- **PII conformance between TS and Python** → v1.5+ (depends on previous item)
- **`petasos[minimal]` extras** → revisit if demand emerges
- **Petasos OpenClaw-equivalent plugin layer** → Hermes isn't OpenClaw; not relevant
- **Bundled-model self-hosting / mirror** → consumer concern; document but don't ship
- **Streaming inputs** → both runtimes do full-buffer; streaming is future research
- **LlamaFirewall / NeMo Guardrails compatibility shims** → evaluate after v1.4 ships
- **Rust port** → speculative; not on roadmap

---

## 13. Relationship to v1.3, v1.5, and the OSS Ecosystem

**v1.3 → v1.4:** Additive on TS side. `Scanner` interface is new and optional. `ClawMoatScanner` continues to work. `OnnxScanner` is the new recommended default for new consumers but not forced. Rule package extraction is internal refactor; exported surface preserved via shim.

**v1.4 → v1.5:** v1.5 (DBR-6 browser sanitization, drafted separately) ships against both runtimes in lockstep using the v1.4 Scanner interface. v1.5 also unblocks the Presidio-on-TS-side work for cross-runtime PII conformance.

**Relationship to LLM Guard / Presidio:** Petasos is not a competitor. Petasos is a session-aware orchestration + escalation + audit + alert layer that composes Presidio + LLM Guard with Drawbridge-specific value-add. Consumers who want raw prompt-injection detection use LLM Guard directly. Consumers who need session-aware escalation, tool-call guard, audit trails, profile-driven tuning, and frequency-based escalation use Petasos (which wraps LLM Guard underneath).

**Relationship to ClawMoat:** ClawMoat remains a supported `Scanner` backend on the TS side. New Drawbridge consumers default to `OnnxScanner` (which converges with Petasos's `LlmGuardScanner` on the same model). ClawMoat's roadmap continues independently; if it adds capabilities (e.g., MCP Scanner, FinanceGuard from v0.8), consumers can compose them via the Scanner interface.

---

## 14. Definition of Done

- [ ] `drawbridge-rules@1.0.0` published to npm and PyPI; conformance corpus present; model pin valid
- [ ] Drawbridge `v1.4.0` published to npm; `Scanner` interface exported; `OnnxScanner` works end-to-end; `MinimalScanner` works; `ClawMoatScanner` continues to work; all v1.3 tests pass
- [ ] Petasos `v1.0.0` published to PyPI; ≥200 tests passing; mypy clean; ruff clean; `pip install petasos` brings working pipeline with Presidio + LLM Guard
- [ ] Cross-runtime conformance suite green: strict deterministic conformance + semantic conformance (within float precision); PII asymmetry catalogued
- [ ] Hermes integration smoke test passes in Petasos CI
- [ ] Wiki: compatibility matrix + Petasos project pages + decision entry + Hermes integration recipe all filed
- [ ] DBR-? tickets for Scanner abstraction, OnnxScanner, Petasos launch filed in Plane
- [ ] Gavin/Hermes dogfood runs 14 days with §7.6 acceptance met
- [ ] DBR-6 (v1.5) unblocked
- [ ] Comprehension entry written per SCHEMA.md "After every merge" routine

---

## Appendix A — Why "Petasos"

The petasos is the broad-brimmed traveler's hat Hermes wears in Greek myth — sometimes winged, always associated with crossing boundaries. Petasos the library does the same job for Hermes the agent framework: it travels alongside, crosses the runtime boundary, carries the same protective discipline Drawbridge offers in Node.

Future names in the same mythological family if cross-runtime story grows: Talaria (winged sandals — speculative Rust port), Caduceus (Hermes' staff — speculative observability surface).

---

## Appendix B — Why the Architecture Pivoted Mid-Spec

The first draft of v1.4 proposed Petasos as a full from-scratch Python port of Drawbridge. A subsequent ecosystem survey surfaced that Microsoft Presidio (PII) and ProtectAI's LLM Guard (semantic scanner backed by DeBERTa-v3) cover most of what we'd otherwise rebuild — and rebuild worse. Architecture B (custom for deterministic / unique pieces, OSS for what they do well) is the result. The model convergence move (both runtimes wrap the same DeBERTa weights via ONNX on Node and native HuggingFace on Python) is what makes the cross-runtime parity story tractable: previously the semantic detection was guaranteed to drift; now it's structurally identical.

This is documented as a reminder for future spec authors: **survey the ecosystem before scoping a port.** The pivot here saved an estimated 60–70% of the implementation work and reduced ongoing maintenance burden by inheriting OSS communities' work on the parts they already do best.
