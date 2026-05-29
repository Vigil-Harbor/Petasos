# PET-6 — Pipeline Orchestration (OSS Tier Complete)

> **Status:** Ready to start
> **Priority:** High
> **Assignee:** Devin
> **Blocks:** PET-7 (Frequency + Escalation), PET-8 (Profiles + Guard), PET-9 (Audit + Alerting)
> **Blocked by:** PET-1 (Core Types + MinimalScanner), PET-3 (LlmGuardScanner), PET-4 (LlamaFirewallScanner), PET-5 (PresidioScanner)

---

## 1. Objective

Implement the `Pipeline` class — the central orchestrator that wires together normalization, pre-filtering, concurrent scanner fan-out, finding merge, fail-mode enforcement, and PII anonymization into a single `await pipeline.inspect()` call. When this lands, the OSS tier is shippable: a developer can `pip install petasos[llm-guard,presidio]`, compose scanners, and get real security coverage with zero premium dependencies. Tag `v0.1.0-alpha.1`.

---

## 2. OSS Landscape — Prior Art Check

| Library / Project | What it does | Gap relative to PET-6 |
|---|---|---|
| [LLM Guard](https://github.com/protectai/llm-guard) (v0.3.16) | 15 input / 20 output scanners, DeBERTa injection model, PII anonymizer | Monolithic pipeline — can't compose third-party backends, no concurrent fan-out, no pluggable fail-mode |
| [prompt-injection-scanner](https://pypi.org/project/prompt-injection-scanner/) | CLI tool for code-level injection detection | Static analysis focus, not runtime message scanning; no pipeline concept |
| [Multi-Agent Defense Pipeline](https://arxiv.org/pdf/2509.14285) (research, 2025) | Sequential/hierarchical chain-of-agents for injection defense | Academic — no library, no Python package, no pluggable backend model |
| [OpenAI Guardrails Python](https://openai.github.io/openai-guardrails-python/) | OpenAI-specific check integration with injection detection | Vendor-locked to OpenAI, not agent-agnostic, no compose-multiple-backends |
| [LangGraph](https://github.com/langchain-ai/langgraph) | General-purpose agent orchestration | Orchestrates agents, not security scanners — no scanner protocol, no finding merge, no fail-mode |

**Conclusion:** No existing Python library provides a pipeline orchestrator that fan-outs to N pluggable scanner backends concurrently, merges findings with position deduplication, and enforces configurable fail-modes. The closest prior art (LLM Guard) is a monolith that becomes one of Petasos's *backends*. PET-6 fills the composition gap.

---

## 3. Scope — Six Pipeline Stages + Config

### 3.1 Pipeline Class (`petasos/pipeline.py`)

The `Pipeline` class accepts a `PetasosConfig` (or kwargs) and exposes a single async entry point:

```python
result = await pipeline.inspect(
    text="some user message",
    direction="inbound",
    session_id="abc-123",
)
```

Stages execute in order:

1. **Normalize** — call `petasos.normalize()` on input text (NFKC, zero-width strip, homoglyph map, RTL detection). Already implemented in `normalize.py`.
2. **Syntactic pre-filter** — run `MinimalScanner` (always, deterministic baseline, zero deps). Already implemented in `scanners/minimal.py`.
3. **Fan-out scan** — run all configured scanners concurrently via `asyncio.gather` with per-scanner exception isolation. Each scanner call is wrapped in a try/except that converts failures to errored `ScanResult` objects — no scanner crash propagates.
4. **Merge findings** — collect findings from all scanners, deduplicate overlapping position ranges (prefer higher-confidence finding), compute aggregate severity (highest severity wins).
5. **Fail-mode enforcement** — evaluate scanner health against the configured mode (`open`/`closed`/`degraded`). Determines `safe` flag on the result.
6. **Anonymize** — if PII findings present and `config.anonymize` is enabled, call Presidio's anonymizer via the `PresidioScanner.anonymize()` function. Supports four modes: `redact`, `replace`, `hash`, `mask`. HMAC-SHA256 for `hash` mode.
7. **Return `PipelineResult`** — `safe`, `findings`, `sanitized_content`, `scanner_results`, `errors`.

### 3.2 PetasosConfig (`petasos/config.py`)

Dataclass matching §3.4 of the spec. Every field JSON-serializable. Validation on construction (e.g., thresholds positive, fail_mode is one of three literals). Premium fields are present and accepted but have no runtime effect until PET-7+ wires them.

Key fields for OSS tier:
- `scanners: list[Scanner]` — configured backends
- `direction: Direction` — default `"inbound"`
- `fail_mode: Literal["open", "closed", "degraded"]` — default `"degraded"`
- `normalize_nfkc`, `strip_zero_width`, `map_homoglyphs`, `detect_rtl_override` — normalization toggles
- `anonymize: bool`, `pii_entities`, `redaction_mode`, `hash_key` — PII settings

### 3.3 Premium Stage Hooks

The pipeline includes clearly marked no-op insertion points:

```python
async def _premium_frequency_hook(self, ...) -> None: ...   # PET-7
async def _premium_escalation_hook(self, ...) -> None: ...  # PET-7
async def _premium_audit_hook(self, ...) -> None: ...       # PET-9
async def _premium_alert_hook(self, ...) -> None: ...       # PET-9
```

These are `async` no-ops that PET-7/8/9 replace with real implementations. The hooks receive the pipeline context (result-so-far, session state) and return updated context. Pattern: method on `Pipeline` that checks `self._premium_active` before doing work.

### 3.4 Finding Deduplication

When multiple scanners flag the same text span, findings with overlapping `Position(start, end)` ranges are grouped. Within each group, the finding with the highest confidence is retained. If confidence ties, the higher severity wins. Non-positioned findings (no position) are always kept.

### 3.5 Fail-Mode Logic

Three modes as specified in NFR-3:

| Mode | Partial ML failure | All ML failure | Syntactic pre-filter |
|---|---|---|---|
| `degraded` (default) | Content passes, reduced coverage | Content blocked | Always runs |
| `open` | Content passes | Content passes | Always runs |
| `closed` | Content blocked | Content blocked | Always runs |

"All ML failure" means every scanner *except* MinimalScanner errored. MinimalScanner is zero-dep pure regex — it cannot fail to load and is never counted as an ML scanner for fail-mode purposes.

---

## 4. Hermes Desktop Platform Considerations

Three footgun sections from `docs/platform/hermes-desktop-footguns.md` directly impact PET-6:

| Footgun | Impact on PET-6 | Mitigation |
|---|---|---|
| **§1 — File tools bypass terminal sandbox** | Pipeline hooks must intercept both `terminal` and `file` tool dispatch paths. A `pre_tool_call` hook covers both, but scanner wrappers around the terminal backend alone miss file-based exfiltration. | Pipeline exposes `inspect()` as the single scan entry point. Integration layer (Hermes side) must call `inspect()` from a `pre_tool_call` hook, not only from terminal dispatch. Document this in the integration recipe. |
| **§2 — Config section wiped by UI model switcher** | Petasos config must be a top-level `petasos:` key, not nested under `model:`. | `PetasosConfig` serializes/deserializes from a `petasos:` top-level YAML key. Validate in tests. |
| **§3 — Config is snapshot-on-start** | Scanner config, fail-mode, and normalization settings are frozen when the session starts. Toggling scanners mid-session has no effect until a new session. | Document the session-boundary behavior. Pipeline constructor snapshots config (defensive copy). No hot-reload of pipeline config — distinct from premium hot-unlock (which changes license state, not pipeline config). |

---

## 5. Decisions Carried Forward

| # | Decision | Rationale |
|---|---|---|
| D1 | `asyncio.gather` with per-scanner exception wrapping, not `asyncio.TaskGroup` | `TaskGroup` (Python 3.11+) cancels siblings on first failure. For a security pipeline, we want all scanners to finish independently — a slow LLM Guard scan shouldn't cancel a fast Presidio scan. `gather(return_exceptions=True)` plus manual result inspection gives the right semantics. |
| D2 | MinimalScanner always runs first, synchronously, before fan-out | MinimalScanner is < 5ms and zero-dep. Running it before fan-out means the syntactic baseline is always available even if `asyncio.gather` hits an edge case. It also provides early-exit data for the pipeline (e.g., a critical syntactic finding could short-circuit in `closed` mode). |
| D3 | Fail-mode defaults to `degraded`, not `open` | Security library — silent failure is worse than brief conservatism. Full rationale in `decisions/2026-05-24-petasos-fail-mode-degraded-default.md`. |
| D4 | Premium hooks are no-op methods on Pipeline, not a plugin/middleware chain | Simplicity over extensibility. Three known premium stages with fixed execution order — a middleware chain adds abstraction without value. Direct method calls are testable, type-safe, and debuggable. |
| D5 | `PetasosConfig` is a standalone dataclass, not subclassed from Drawbridge config | Petasos is uncoupled from Drawbridge. Own config shape, own serialization, own validation. No inheritance, no shared schema. |
| D6 | Pipeline constructor takes a defensive copy of config | Per §3 (snapshot-on-start): mutating the config object after pipeline construction must not change pipeline behavior. `copy.deepcopy` on construction. |

---

## 6. Done When

- [ ] Pipeline runs end-to-end with 0, 1, 2, or 3 scanners configured
- [ ] Concurrent scanner execution verified (scanners run in parallel, not sequentially — timing assertions in tests)
- [ ] Finding deduplication works for overlapping position ranges across scanners
- [ ] Fail-mode `degraded`: partial ML failure → pass; all ML failure → block; syntactic always runs
- [ ] Fail-mode `open`: any failure → pass
- [ ] Fail-mode `closed`: any failure → block
- [ ] Anonymization produces correct redaction for all four operator modes (redact, replace, hash, mask)
- [ ] HMAC-SHA256 hash mode produces deterministic, correlatable hashes across calls
- [ ] Pipeline never throws — all error paths return valid `PipelineResult`
- [ ] Latency: syntactic-only < 5ms, single ML scanner < 100ms, full pipeline < 250ms (CPU)
- [ ] `PetasosConfig` serializes to/from JSON correctly, validates on construction
- [ ] Config uses top-level `petasos:` key (not nested under `model:` — Hermes §2 compliance)
- [ ] Pipeline constructor snapshots config (defensive copy — mutation after construction is inert)
- [ ] Premium hooks are present as no-ops, callable without error
- [ ] `mypy --strict` and `ruff` clean
- [ ] ≥60 tests (pipeline + config + merge + fail-mode + anonymization integration)
- [ ] Tag `v0.1.0-alpha.1` — OSS tier is shippable

---

## 7. Out of Scope

- **Frequency tracking / escalation tiers** — PET-7 (premium hooks are stubs only)
- **Profile system / ToolCallGuard** — PET-8
- **Audit trails / alert rules** — PET-9
- **JWT license validation** — PET-10 (premium gate is a simple flag for now)
- **Hermes integration testing** — PET-11 (PET-6 tests are standalone)
- **PyPI publish** — PET-12
- **Pipeline config hot-reload** — explicitly out of scope per §3 snapshot-on-start
- **Custom middleware / plugin hooks** — decision D4 rejects this for now

---

## 8. Key Files to Produce

```
petasos/
├── pipeline.py            # Pipeline class — central orchestrator
├── config.py              # PetasosConfig dataclass + validation
tests/
├── test_pipeline.py       # Pipeline orchestration tests (≥40)
├── test_config.py         # Config validation + serialization tests (≥10)
├── test_finding_merge.py  # Deduplication + severity aggregation tests (≥10)
```

---

## 9. Technical Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `asyncio.gather` fan-out introduces non-deterministic test failures | Medium | Use deterministic mock scanners with controlled timing in unit tests. Reserve real-backend concurrency for PET-11 integration tests. |
| Finding dedup algorithm is O(n²) for many overlapping findings | Low | Practical finding count is < 50 per scan. Sort by position, sweep once. Optimize only if profiling shows a problem. |
| Presidio anonymizer import adds latency even when no PII found | Low | Lazy-import `presidio-anonymizer` only when anonymization is triggered and PII findings exist. Gate behind `config.anonymize and pii_findings`. |
| Config defensive copy (`deepcopy`) is slow for large scanner lists | Low | Scanner instances are lightweight. Profile if config construction exceeds 1ms. |
| Premium hook signature changes during PET-7/8/9 | Medium | Define hook signatures generously (accept `**kwargs` for forward compatibility). Write integration contract tests that PET-7/8/9 must satisfy. |

---

## 10. Implementation Sequence (suggested)

1. **PetasosConfig** — `config.py` with all fields, JSON serialization, validation, defensive copy helper. Tests.
2. **Finding merge** — standalone function for deduplication + severity aggregation. Tests.
3. **Pipeline skeleton** — `pipeline.py` with constructor, `inspect()` method, stage calls in order. Wire normalization + MinimalScanner first (no external scanners).
4. **Fan-out scan** — `asyncio.gather` with exception isolation. Test with mock scanners.
5. **Fail-mode enforcement** — three-mode logic. Test all nine cases (3 modes × 3 failure states).
6. **Anonymization integration** — wire Presidio anonymizer call, gated by config + PII findings.
7. **Premium hooks** — add no-op methods at correct pipeline positions. Verify they're callable.
8. **Gate verification** — run full suite, latency benchmarks, `mypy --strict`, `ruff`, tag alpha.

---

## 11. Spec Traceability

| Requirement | Spec Reference |
|---|---|
| Pipeline orchestration (normalize → pre-filter → scan → merge → result) | FR-3 |
| Configuration-first design, JSON-serializable config | FR-4 |
| Input + output scanning (direction parameter) | FR-5 |
| Pipeline latency budget | NFR-2 |
| Configurable fail-mode (default: degraded) | NFR-3 |
| Zero required ML deps at base install | NFR-4 |
| Pipeline never throws | FR-3, spec §3.3 |
| PII anonymization with configurable operators | FR-2 |
| Hot-unlock enforcement point (premium hook scaffold) | DC-8 |
