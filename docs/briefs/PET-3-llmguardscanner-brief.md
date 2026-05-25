# PET-3 · LlmGuardScanner Wrapper — Implementation Brief

> **Parent:** PET-2 (OSS Scanner Wrappers)
> **Phase:** 2 · **Blocked by:** PET-1 · **Blocks:** PET-6
> **Parallel with:** PET-4, PET-5
> **Spec traceability:** FR-1 (pluggable backends), NFR-4 (extras-based install)
> **File:** `petasos/scanners/llm_guard.py`
> **Extras:** `pip install petasos[llm-guard]` → `llm-guard>=0.3.16,<0.4`

---

## Objective

Wrap Protect AI's [LLM Guard](https://github.com/protectai/llm-guard) behind Petasos's `Scanner` protocol. LLM Guard ships 15 input scanners; we expose the five most relevant to agent security: PromptInjection, Toxicity, BanTopics, InvisibleText, and Secrets. The wrapper lazy-loads `llm_guard` on first use so the base `petasos` install stays zero-ML-dep.

---

## Decisions Carried Forward

### D1 — Lazy-load, not import-time gate

The `llm_guard` package is imported inside a private `_ensure_loaded()` method called on first `scan()`. If the import fails, the scanner returns an errored `ScanResult` with `error="llm-guard not installed. pip install petasos[llm-guard]"` and empty findings — it does **not** raise. This extends MinimalScanner's try/except-in-scan pattern (which catches runtime errors) with a **new** lazy-load layer for optional dependencies. The "pipeline never throws" invariant applies.

### D2 — Per-scanner instantiation, not `scan_prompt()` orchestrator

LLM Guard's `scan_prompt()` runs an array of scanners and returns aggregate results. We **do not** use it. Each sub-scanner (PromptInjection, Toxicity, etc.) is instantiated individually and called via its `.scan(prompt)` method. Reason: `scan_prompt()` hides per-scanner attribution — we need individual `ScanFinding` objects with `finding_type` and `scanner_name` populated for pipeline merge and dedup.

### D3 — Threshold mapping

LLM Guard scanners return a `(sanitized_prompt, is_valid, risk_score)` tuple. The `risk_score` is a float 0.0–1.0. We map:

- `risk_score` → `ScanFinding.confidence`
- `is_valid == False` → finding emitted
- `is_valid == True` → no finding (below threshold)

The constructor's `threshold` (default 0.85) is passed to `PromptInjection(threshold=...)`. Other sub-scanners use their own default thresholds unless future work exposes them.

### D4 — Finding type taxonomy

Each LLM Guard sub-scanner maps to a `finding_type`:

| Sub-scanner | `finding_type` | `rule_id` prefix |
|---|---|---|
| PromptInjection | `"injection"` | `petasos.llmguard.injection` |
| Toxicity | `"toxicity"` | `petasos.llmguard.toxicity` |
| BanTopics | `"policy"` | `petasos.llmguard.ban-topics` |
| InvisibleText | `"encoding"` | `petasos.llmguard.invisible-text` |
| Secrets | `"credential"` | `petasos.llmguard.secrets` |

Severity: PromptInjection → `HIGH`, Toxicity → `MEDIUM`, BanTopics → `MEDIUM`, InvisibleText → `MEDIUM`, Secrets → `HIGH`.

### D5 — Severity and confidence are immutable per scan

LLM Guard scanners don't expose position data in their output — findings are whole-prompt-level, not span-level. `ScanFinding.position` will be `None` for all LlmGuardScanner findings. `matched_text` will also be `None`. This is a known limitation documented in the scanner's docstring.

### D6 — Enable flags default conservative

Only PromptInjection and InvisibleText are on by default. Toxicity, Secrets, and BanTopics are opt-in — they add latency (model loads) and have higher false-positive rates for general agent use.

### D7 — LLM Guard model download happens on first scan

LLM Guard downloads DeBERTa-v3 weights on first invocation. This is a ~180MB one-time cost. The wrapper does **not** pre-download models at init time. A future CLI `petasos warmup` command may address this (out of scope for PET-3).

### D8 — No output scanner integration

LLM Guard has 20 output scanners. PET-3 wraps input scanners only. Output scanning uses the same `direction="outbound"` parameter on `scan()`, but runs the same input scanners against outbound text. If LLM Guard output-specific scanners are needed later, that's a separate work item.

### D9 — Platform: Windows subprocess concern is N/A

LLM Guard runs in-process (Python model inference), no subprocess spawning. The Hermes Desktop Windows footgun (SIGTERM unreliable for subprocesses) does not apply here.

---

## Done When

- [ ] `LlmGuardScanner` class in `petasos/scanners/llm_guard.py` implements the `Scanner` protocol
- [ ] Lazy-load pattern: `import llm_guard` fails → returns errored `ScanResult`, no crash
- [ ] Constructor params: `threshold`, `enable_toxicity`, `enable_secrets`, `enable_invisible_text`, `enable_ban_topics`, `ban_topics`
- [ ] Each enabled sub-scanner produces correctly typed `ScanFinding` objects (rule_id, finding_type, severity, confidence, scanner_name all populated)
- [ ] `name` property returns `"llm_guard"`
- [ ] Duration tracking via `time.perf_counter` (same pattern as MinimalScanner)
- [ ] Integration tests against real `llm-guard` backend (not mocked) with 20-message corpus
- [ ] `pip install petasos[llm-guard]` succeeds in clean Python 3.11 venv
- [ ] Fail-open verified under backend exception (not just import failure)
- [ ] ≥15 tests passing
- [ ] `mypy --strict` clean
- [ ] `ruff check` / `ruff format` clean

---

## Out of Scope

- **Model pre-download / warmup CLI** — latency of first invocation is accepted; warming is a future concern.
- **Output-specific scanners** — LLM Guard's 20 output scanners are not wrapped. `direction="outbound"` runs the same input scanners.
- **Per-sub-scanner threshold tuning** — only PromptInjection threshold is exposed. Other sub-scanners use library defaults.
- **Batch/async model inference** — LLM Guard's scanners are synchronous; we wrap in `asyncio.to_thread` or equivalent if needed, but do not implement custom batching.
- **Custom model selection** — LLM Guard supports custom models for PromptInjection; we use the default DeBERTa-v3 model. Custom model config is future work.
- **Pipeline integration** — that's PET-6. This scanner is a standalone unit that the pipeline will consume.
- **Frequency, escalation, profiles** — premium tier (PET-7+).
