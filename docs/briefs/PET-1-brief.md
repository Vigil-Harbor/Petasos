# PET-1 — Repo Bootstrap + Core Types + MinimalScanner + Normalization

> **Status:** In Progress (Plane: `e693b18a`, started 2026-05-24)
> **Priority:** High
> **Assignee:** Devin
> **Blocks:** PET-2 (Scanner Wrappers), PET-6 (Pipeline)
> **Blocked by:** Nothing — first item in the graph

---

## 1. Objective

Stand up the Petasos greenfield repo with every core abstraction that downstream work items depend on: the Scanner protocol, type system, 17-rule syntactic scanner, and Unicode normalization layer. When this lands, three parallel scanner-wrapper squads (PET-3/4/5) can start immediately.

---

## 2. OSS Landscape — Prior Art Check

Existing Python libraries that overlap with PET-1's scope:

| Library | What it does | Gap relative to Petasos |
|---------|-------------|------------------------|
| [LLM Guard](https://github.com/protectai/llm-guard) (v0.3.16) | 15 input / 20 output scanners, DeBERTa injection model, PII anonymizer | Monolithic — no unified Scanner protocol, no session awareness, heavy deps at import |
| [Pytector](https://github.com/MaxMLang/pytector) | DeBERTa/DistilBERT injection detection + regex PII | Single-backend, no composability, no normalization layer |
| [Vigil-LLM](https://github.com/deadbits/vigil-llm) | REST-based scanner with embeddings, YARA rules | REST sidecar model (Petasos is in-process), no frequency/escalation |
| [prompt-injection-detector](https://pypi.org/project/prompt-injection-detector/) | FastAPI gateway with risk scoring | Gateway model, not a composable library protocol |
| [OpenAI Guardrails Python](https://openai.github.io/openai-guardrails-python/) | OpenAI-specific check integration | Vendor-locked, not agent-agnostic |

**Conclusion:** No existing library provides a Scanner protocol + compose-multiple-backends + zero-dep syntactic baseline + Unicode normalization in a single lightweight package. Petasos fills a real gap. The closest prior art (LLM Guard) becomes a *backend* that Petasos wraps — not a competitor.

---

## 3. Scope — Four Deliverables

### 3.1 Repo Scaffolding

- `pyproject.toml` — Hatch build backend, Python ≥3.11, optional extras (`llm-guard`, `llamafirewall`, `presidio`, `all`)
- `ruff.toml` — lint + format config
- `mypy --strict` configuration
- `pytest` test runner, `pytest-asyncio` for async scanner tests
- `.gitignore`, `py.typed` (PEP 561)
- GitHub Actions CI stub (lint → type-check → test matrix)

### 3.2 Core Types (`petasos/_types.py`)

| Type | Role |
|------|------|
| `Scanner` (Protocol) | Load-bearing abstraction — every backend implements `name` + `async scan()` |
| `ScanResult` | Per-scanner output: `findings`, `error`, `scanner_name`, `duration_ms` |
| `ScanFinding` | Single detection: `rule_id`, `finding_type`, `severity`, `confidence`, `position`, `message` |
| `Direction` | Literal `"inbound" \| "outbound"` |
| `Severity` | Literal levels: `critical`, `high`, `medium`, `low`, `info` |
| `PipelineResult` | Aggregate: `safe` bool, all findings, sanitized content, scanner metadata, premium manifest |
| `NormalizedText` | Wrapper carrying original + normalized form + normalization metadata |

Design constraints:
- All result types are frozen dataclasses (immutable after construction)
- `PipelineResult.error` carries caught exceptions — pipeline never throws

### 3.3 MinimalScanner (`petasos/scanners/minimal.py`)

Port Drawbridge's 17 syntactic rules from `clawmoat-drawbridge-sanitizer/src/validation/index.ts` → `SYNTACTIC_RULES`.

**Source rule taxonomy (verified against Drawbridge source):**

| Category | Rules | Rule IDs |
|----------|-------|----------|
| Injection patterns | 8 | `ignore-previous`, `ignore-all`, `disregard`, `you-are-now`, `new-instructions`, `system-override`, `system-prefix`, `inst-delimiter` |
| Role-switch triggers | 2 | `role-switch-capability` (role-switch + capability co-occur), `role-switch-only` |
| Structural checks | 3 | `oversized-payload`, `excessive-depth`, `binary-content` |
| Encoding tricks | 4 | `base64-in-text`, `invisible-chars`, `homoglyph-substitution`, `rtl-override` |
| **Total** | **17** | |

Port notes:
- Rule IDs get Petasos namespace: `petasos.syntactic.<category>.<slug>`
- Regex patterns are Python `re` (IGNORECASE, MULTILINE where needed)
- Structural checks use configurable thresholds (payload size, JSON depth)
- Input is NFKC-normalized before regex matching (normalization module dependency)
- Scanner implements the `Scanner` protocol: `async def scan(...)` returns `ScanResult`

### 3.4 Normalization Module (`petasos/normalize.py`)

| Transform | Technique |
|-----------|-----------|
| Unicode NFKC | `unicodedata.normalize("NFKC", text)` |
| Zero-width stripping | Remove U+200B, U+200C, U+200D, U+FEFF, U+2060 |
| Homoglyph mapping | Curated confusables table (Cyrillic→Latin, Greek→Latin, math symbols) — not full ICU confusables (too large for zero-dep) |
| RTL override detection | Detect U+202E, U+202D, U+2066–U+2069 — flag as finding, don't strip (preserve semantics) |

Returns `NormalizedText` with: `original`, `normalized`, `transformations_applied` (list of which transforms fired).

---

## 4. Decisions Carried Forward

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Curated homoglyph table, not full ICU confusables | Full table is ~8K entries, adds import weight. Curated subset covers the attack-relevant Cyrillic/Greek/math substitutions. Expand later if evasion demonstrates gaps. |
| D2 | `petasos.*` namespace for rule IDs (not `drawbridge.*`) | Petasos is uncoupled from Drawbridge — own identity, own release cadence. Heritage acknowledged in comments, not in runtime identifiers. |
| D3 | Frozen dataclasses for all result types | Security library — mutation after construction is a bug vector. Defensive copies are the norm for Drawbridge's TypeScript `Object.freeze`; Python equivalent is `@dataclass(frozen=True)`. |
| D4 | `pytest-asyncio` for scanner testing | Scanner protocol is async. Testing without asyncio fixtures creates sync/async mismatch and hides concurrency bugs. |
| D5 | RTL override: detect and flag, don't strip | Stripping RTL controls breaks legitimate bidirectional text. Detection-only preserves content fidelity while alerting to evasion attempts. |

---

## 5. Done When

- [ ] `pip install -e .` succeeds in a clean Python 3.11 venv (base install, zero ML deps)
- [ ] `mypy --strict .` passes with zero errors
- [ ] `ruff check . && ruff format --check .` passes
- [ ] `MinimalScanner` detects all 17 rule categories against a fixed test corpus
- [ ] Normalization strips zero-width chars, maps confusable homoglyphs, flags RTL overrides
- [ ] ≥50 tests passing (`pytest` green)
- [ ] `Scanner` protocol can be implemented by a trivial stub (verify in `test_types.py`)
- [ ] All result types are frozen (mutation raises `FrozenInstanceError`)
- [ ] GitHub Actions CI stub runs lint + typecheck + tests

---

## 6. Out of Scope

- **ML scanner backends** — PET-3/4/5 handle LLM Guard, LlamaFirewall, Presidio wrappers
- **Pipeline orchestration** — PET-6 (depends on this item but is separate)
- **Frequency tracking / escalation** — PET-7 (Premium tier)
- **JWT license validation** — PET-10
- **PyPI publish** — PET-12
- **Hermes integration testing** — PET-11
- **Custom profiles / tool call guard** — PET-8
- **Any network calls at runtime** — Petasos is offline-first by design

---

## 7. Technical Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Homoglyph table gaps allow evasion | Medium | Ship curated subset now; track bypass reports; expand table in patch releases |
| `re` module perf on large payloads | Low | Structural `oversized-payload` rule fires before regex fan-out; configurable threshold caps input size |
| Frozen dataclass serialization friction | Low | Provide `.to_dict()` / `.from_dict()` helpers on result types for JSON round-trip |
| Python 3.11 floor excludes some users | Low | Hermes requires 3.11+; ecosystem has moved past 3.9 |

---

## 8. Implementation Sequence (suggested)

1. **Scaffolding** — `pyproject.toml`, `ruff.toml`, `.gitignore`, `py.typed`, empty `petasos/__init__.py`
2. **Core types** — `_types.py` with all protocol + dataclass definitions, `test_types.py`
3. **Normalization** — `normalize.py` + `test_normalize.py`
4. **MinimalScanner** — `scanners/minimal.py` + `test_minimal_scanner.py` (depends on normalization + types)
5. **CI stub** — `.github/workflows/ci.yml`
6. **Gate verification** — run all checks, confirm ≥50 tests, tag as ready for PET-2 unblock
