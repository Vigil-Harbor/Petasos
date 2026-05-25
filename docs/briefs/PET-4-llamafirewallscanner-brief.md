# PET-4 · LlamaFirewallScanner Wrapper — Implementation Brief

> **Parent:** PET-2 (OSS Scanner Wrappers)
> **Phase:** 2 · **Blocked by:** PET-1 · **Blocks:** PET-6
> **Parallel with:** PET-3, PET-5
> **Spec traceability:** FR-1 (pluggable backends), NFR-4 (extras-based install)
> **File:** `petasos/scanners/llama_firewall.py`
> **Extras:** `pip install petasos[llamafirewall]` → `llamafirewall` (unpinned — Meta hasn't stabilized semver yet; v1.0.3 current)

---

## Objective

Wrap Meta's [LlamaFirewall](https://github.com/meta-llama/PurpleLlama/tree/main/LlamaFirewall) behind Petasos's `Scanner` protocol. LlamaFirewall provides three detection components: PromptGuard 2 (jailbreak/injection), AlignmentCheck (chain-of-thought auditing), and CodeShield (unsafe code static analysis). The wrapper exposes all three behind toggle flags with PromptGuard enabled by default.

---

## Decisions Carried Forward

### D1 — LlamaFirewall API surface: `LlamaFirewall` class, not raw scanners

LlamaFirewall's public API uses a top-level `LlamaFirewall` class that takes a `scanners` dict mapping `Role` to `ScannerType` lists. We instantiate this class rather than reaching into individual scanner implementations. Reason: Meta's API is designed around the orchestrator; individual scanner classes (`PromptGuardScanner`, `AlignmentCheckScanner`, `CodeShieldScanner`) are internal and may change.

```python
from llamafirewall import LlamaFirewall, UserMessage, Role, ScannerType

fw = LlamaFirewall(scanners={
    Role.USER: [ScannerType.PROMPT_GUARD],
})
result = fw.scan(UserMessage(content="..."))
```

We map the `scanners` dict dynamically based on which enable flags are `True`.

### D2 — Lazy-load with clear ImportError

Same pattern as PET-3. `llamafirewall` is imported inside a `_ensure_loaded()` method called on first `scan()`. This is a **new** lazy-load layer for optional deps, extending MinimalScanner's try/except-in-scan pattern. Import failure → errored `ScanResult` with install instructions. No raise.

### D3 — LlamaFirewall's `ScanResult` → Petasos's `ScanResult`

LlamaFirewall returns its own `ScanResult` with fields: `decision` (ALLOW/BLOCK), `reason`, `score`. We map:

| LlamaFirewall field | Petasos field |
|---|---|
| `decision == BLOCK` | Finding emitted |
| `decision == ALLOW` | No finding |
| `score` | `ScanFinding.confidence` |
| `reason` | `ScanFinding.message` |

### D4 — Finding type taxonomy

| Component | `finding_type` | `rule_id` prefix | Default severity |
|---|---|---|---|
| PromptGuard 2 | `"injection"` | `petasos.llamafirewall.prompt-guard` | `HIGH` |
| AlignmentCheck | `"alignment"` | `petasos.llamafirewall.alignment-check` | `HIGH` |
| CodeShield | `"unsafe_code"` | `petasos.llamafirewall.code-shield` | `MEDIUM` |

### D5 — AlignmentCheck requires chain-of-thought input

AlignmentCheck audits the model's reasoning trace, not raw user input. For `direction="inbound"`, it's meaningful only if the text contains CoT (e.g., tool-use planning). For `direction="outbound"`, it inspects model output for goal hijacking. The scanner runs it regardless of direction when enabled — false negatives on non-CoT input are acceptable (it simply won't flag anything).

### D6 — CodeShield runs on both directions

CodeShield performs static analysis on code blocks. Inbound: catches injected code in user messages. Outbound: catches unsafe code the model generates. We run it whenever enabled, regardless of `direction`.

### D7 — PromptGuard model variants: use default (86M)

Meta ships PromptGuard 2 in 86M and 22M variants. The 22M variant reduces latency but has lower accuracy. We use whatever `llamafirewall` defaults to (currently 86M). Custom model selection is out of scope.

### D8 — LlamaFirewall's `scan()` is synchronous

LlamaFirewall's `scan()` is a synchronous call. Our `Scanner.scan()` is `async`. We wrap in `asyncio.to_thread()` to avoid blocking the event loop during model inference. This adds trivial overhead but preserves pipeline concurrency (PET-6 runs scanners via `asyncio.gather`).

### D9 — No position/span data

LlamaFirewall returns whole-message verdicts, not character-level spans. `ScanFinding.position` and `matched_text` will be `None`. Same limitation as PET-3.

### D10 — Platform: Windows subprocess concern — monitor

LlamaFirewall may use `torch.multiprocessing` or spawn subprocesses for model inference depending on configuration. On Windows (Hermes Desktop), SIGTERM is unreliable for child processes. For PET-4, we document this as a known risk but do not implement platform-specific process handling — it will be evaluated during PET-6 integration testing on Windows.

### D11 — `llamafirewall` version pinning

The `pyproject.toml` extra is unpinned (`"llamafirewall"` with no version constraint). Meta is at v1.0.3 and hasn't committed to semver stability. We accept breakage risk and will pin after they ship a stable release. Integration tests will catch API breaks.

---

## Done When

- [ ] `LlamaFirewallScanner` class in `petasos/scanners/llama_firewall.py` implements the `Scanner` protocol
- [ ] Lazy-load pattern: `import llamafirewall` fails → returns errored `ScanResult`, no crash
- [ ] Constructor params: `enable_prompt_guard`, `enable_alignment_check`, `enable_code_shield`
- [ ] Dynamic `scanners` dict built from enable flags
- [ ] `scan()` wraps synchronous LlamaFirewall call in `asyncio.to_thread()`
- [ ] Finding mapping: BLOCK → finding with correct rule_id, finding_type, severity, confidence, message
- [ ] `name` property returns `"llama_firewall"`
- [ ] Duration tracking via `time.perf_counter`
- [ ] Integration tests against real `llamafirewall` backend (not mocked) with 20-message corpus
- [ ] `pip install petasos[llamafirewall]` succeeds in clean Python 3.11 venv
- [ ] Fail-open verified under backend exception (not just import failure)
- [ ] ≥15 tests passing
- [ ] `mypy --strict` clean
- [ ] `ruff check` / `ruff format` clean

---

## Out of Scope

- **PromptGuard 22M variant selection** — use default model. Custom model config is future work.
- **Custom regex filter integration** — LlamaFirewall supports custom regex scanners; we don't expose this (MinimalScanner handles regex).
- **Windows process signal handling** — documented risk, not mitigated in PET-4. Evaluate at PET-6 integration.
- **AlignmentCheck model fine-tuning** — use Meta's default alignment model.
- **Pipeline integration** — PET-6 consumes this scanner.
- **Frequency, escalation, profiles** — premium tier (PET-7+).
- **Batch scanning / multi-message context** — LlamaFirewall supports multi-turn conversation context; we scan single messages per the `Scanner` protocol. Multi-turn awareness is a future enhancement.
