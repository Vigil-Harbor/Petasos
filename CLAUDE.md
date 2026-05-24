# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Petasos is a pluggable, session-aware content security pipeline for Python AI agents. It composes OSS scanners (LLM Guard, LlamaFirewall, Presidio) behind a unified `Scanner` protocol, adds session-aware orchestration (frequency tracking, escalation tiers, profile-driven tuning, tool call guard), and exposes every configuration surface for frontend binding. Published on PyPI as `petasos`.

Primary consumer: Hermes Agent (Nous Research, Python 3.11+). Petasos imports in-process as a Python library — no sidecar, no REST, no subprocess.

### Two Consumer Platforms

Hermes Desktop ships on macOS (native) and Windows (.exe / Electron). The macOS integration path is well-documented in the wiki. The Windows path has platform-specific footguns — see `docs/platform/hermes-desktop-footguns.md` for the full report. Key differences: file tools bypass the terminal sandbox, hooks spawn via Git Bash (MINGW64) adding 100-200ms, config sections get wiped by the UI model switcher, and process signal handling diverges. PET-6 through PET-11 must account for both platforms.

Petasos is Drawbridge-*inspired* but fully uncoupled — own repo, own ticket prefix (PET), own release cadence, own threat model. No shared rule package, no cross-runtime conformance with Drawbridge.

## Status

Greenfield project. The active spec is `petasos-spec.md`; work items are in `petasos-work-items.md`. The file `petasos-project-spec-DRAFT-PARKED.md` is a superseded earlier draft preserved for reference — it proposed Drawbridge coupling that was explicitly rejected.

## Build & Run

```bash
pip install -e .                    # base install (no ML deps)
pip install -e ".[llm-guard]"       # + LLM Guard scanner
pip install -e ".[llamafirewall]"   # + LlamaFirewall scanner
pip install -e ".[presidio]"        # + Presidio PII scanner
pip install -e ".[all]"             # all scanner backends

# Tooling
ruff check .                        # lint
ruff format .                       # format
mypy --strict .                     # type check
pytest                              # run all tests
pytest tests/test_minimal_scanner.py # single test file
pytest -k "test_normalize"          # single test by name
pytest --cov                        # coverage report
```

Build backend is Hatch (`pyproject.toml`).

## Architecture

### OSS / Premium Split

Detection is free, session intelligence is paid. OSS tier: scanner protocol + pluggable backends + syntactic pre-filter + normalization + PII anonymization. Premium tier (license-gated via signed JWT, hot-unlock): frequency tracking, escalation tiers, profiles, tool call guard, audit trails, alerting.

### Scanner Protocol

The load-bearing abstraction. Every detection backend implements:

```python
class Scanner(Protocol):
    @property
    def name(self) -> str: ...
    async def scan(self, text: str, *, direction: Direction = "inbound",
                   session_id: str | None = None) -> ScanResult: ...
```

Four backends: `MinimalScanner` (17 regex rules, zero deps, always ships), `LlmGuardScanner` (extras), `LlamaFirewallScanner` (extras), `PresidioScanner` (extras).

### Pipeline Stages

```
Input → Normalize (NFKC, zero-width, homoglyph, RTL)
  → Syntactic pre-filter (17 rules, always runs)
  → Fan-out to N scanners (asyncio.gather)
  → Merge findings (dedup overlapping positions)
  → [Premium] Frequency update → Escalation check
  → Anonymize (if PII + enabled)
  → [Premium] Audit → Alerting
  → PipelineResult
```

### Target Layout

```
petasos/
├── __init__.py
├── _types.py            # Scanner protocol, ScanResult, ScanFinding, Direction, etc.
├── normalize.py
├── pipeline.py          # Pipeline class — central orchestrator
├── config.py            # PetasosConfig dataclass
├── scanners/
│   ├── minimal.py       # MinimalScanner (zero-dep, 17 regex rules)
│   ├── llm_guard.py     # LlmGuardScanner (extras: llm-guard)
│   ├── llama_firewall.py # LlamaFirewallScanner (extras: llamafirewall)
│   └── presidio.py      # PresidioScanner + anonymization (extras: presidio)
├── premium/
│   ├── frequency.py     # FrequencyTracker (exp decay + rolling window)
│   ├── escalation.py    # 3-tier escalation (Tier 3 cannot be disabled)
│   ├── profiles.py      # 5 built-in + custom profiles
│   ├── guard.py         # ToolCallGuard
│   ├── audit.py         # AuditEmitter (verbosity-gated)
│   ├── alerting.py      # AlertManager (5 rules + rate limiting)
│   └── license.py       # JWT validation (local, no network)
```

## Key Design Invariants

- **Pipeline never throws** — all errors caught and returned in `PipelineResult`.
- **Fail-mode defaults to `degraded`** — partial scanner failure passes content; all ML scanners down blocks content; syntactic pre-filter (zero deps) always runs. Configurable to `open` or `closed`.
- **Zero required ML deps at base install** — scanner backends are pip extras, not hard deps. `pip install petasos` is lightweight; `pip install petasos[all]` is ~300MB.
- **Frozen exports** — built-in profiles, rules, and default configs must be immutable (defensive copies, frozen dataclasses).
- **Tier 3 escalation cannot be disabled** — hardcoded floor, no config override.
- **Premium enforcement is hot-unlock** — `petasos.activate(key)` or `PETASOS_LICENSE_KEY` env var. JWT validated locally (bundled public key), no network at runtime. Pipeline never reconstructed on key change.

## Test Standards

- Target: 300+ tests, 90%+ line coverage on pipeline/frequency/guard/audit/alerting.
- Scanner wrappers use integration tests against real backends, not mocks.
- Latency budgets: syntactic-only < 5ms, single ML scanner < 100ms, full pipeline < 250ms (CPU).

## Plan & Spec Reviews

- Always verify load-bearing claims against the actual codebase, wiki, and current file state — never review from memory or stale buffers.
- Re-read files at the start of each new review pass; the user iterates specs frequently and stale context produces false-positive findings.
- Deliver findings as severity-ranked lists (critical/high/medium/low) with specific references.

## Project Management

- Petasos tracks under the `PET` project in Plane (UUID `5bff6316-84ea-4103-b9e2-4861ac9c226a`).
- Work items PET-1 through PET-12 are defined in `petasos-work-items.md` with a dependency graph. PET-2 is a parent container; PET-3/4/5 are its children (scanner wrappers).
- When creating Plane work items, set `description_html` (the canonical field).
- Drawbridge syntactic rules source: `clawmoat-drawbridge-sanitizer/src/validation/index.ts` → `SYNTACTIC_RULES` export.
- Drawbridge FrequencyTracker source: `clawmoat-drawbridge-sanitizer/src/frequency/index.ts`.

## Wiki

The Vigil Harbor wiki lives at `C:\Users\zioni\Documents\Vigil-Harbor\vigil-harbor-wiki`. Read `SCHEMA.md` for conventions. After completing work: update filemap/state for Petasos, create `decisions/` entries for judgment calls, append to `log.md`.

## Git Hygiene

- Before committing, audit staged paths for build artifacts, `.eggs/`, `dist/`, `*.egg-info/`, `__pycache__/`, model files, and large binaries.
- Never run broad cleanup commands unscoped.
