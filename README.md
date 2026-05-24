# Petasos

Pluggable, session-aware content security pipeline for Python AI agents.

Petasos composes OSS scanners ([LLM Guard](https://github.com/protectai/llm-guard), [LlamaFirewall](https://github.com/meta-llama/LlamaFirewall), [Presidio](https://github.com/microsoft/presidio)) behind a unified `Scanner` protocol, adds session-aware orchestration (frequency tracking, escalation tiers, profile-driven tuning, tool call guard), and exposes every configuration surface for frontend binding.

## Install

```bash
pip install petasos                    # base install (zero ML deps)
pip install petasos[llm-guard]         # + LLM Guard scanner
pip install petasos[llamafirewall]     # + LlamaFirewall scanner
pip install petasos[presidio]          # + Presidio PII scanner
pip install petasos[all]               # all scanner backends
```

Requires Python 3.11+.

## What ships at each tier

| Tier | What you get |
|------|-------------|
| **OSS** (free) | Scanner protocol, pluggable backends, 17-rule syntactic pre-filter, Unicode normalization, PII anonymization |
| **Premium** (license-gated) | Frequency tracking, 3-tier escalation, profiles, tool call guard, audit trails, alerting |

Premium unlocks at runtime via `petasos.activate(key)` or `PETASOS_LICENSE_KEY` env var. JWT validated locally — no network calls at runtime.

## Scanner protocol

Every detection backend implements:

```python
class Scanner(Protocol):
    @property
    def name(self) -> str: ...

    async def scan(
        self, text: str, *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult: ...
```

## Pipeline

```
Input → Normalize (NFKC, zero-width, homoglyph, RTL)
  → Syntactic pre-filter (17 rules, always runs)
  → Fan-out to N scanners (asyncio.gather)
  → Merge findings (dedup overlapping positions)
  → [Premium] Frequency → Escalation
  → Anonymize (if PII + enabled)
  → [Premium] Audit → Alerting
  → PipelineResult
```

The pipeline never throws — all errors are caught and returned in `PipelineResult`. Fail-mode defaults to `degraded`: partial scanner failure passes content; all ML scanners down blocks content; the syntactic pre-filter (zero deps) always runs.

## Status

Pre-release. Work items tracked as PET-1 through PET-12 in `petasos-work-items.md`.

## License

TBD
