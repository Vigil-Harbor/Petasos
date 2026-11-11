# Repository guidance

Petasos is a Python content-security library and a Hermes Agent plugin. The library owns configuration, scanner composition and tool-call policy. Hermes supplies plugin loading, settings writes, approvals, redaction and the dashboard that serves the Petasos tab.

## Run the gate

Use Python 3.11 or newer and install the `dev` extra for development. This machine's tools are `.venv/bin/python`, `.venv/bin/ruff` and `.venv/bin/mypy`; run them with the checkout as the working directory.

```bash
ruff check .
ruff format --check .
mypy --strict .
python -m pytest -q
```

Regenerate references with `python -m scripts.generate_reference`. The test suite regenerates them into a temporary directory and compares every file. It also runs documentation examples and checks relative links. Change schema metadata or parser help at its source rather than editing generated pages.

## Layout

| Path | Owns |
|---|---|
| `petasos/__init__.py`, `model.py` | Stable exports and scanner/result types. |
| `petasos/config/` | Schema, sections, jobs, strictness, resolution, secrets and migration. |
| `petasos/scanners/registry.py` | The one config-to-scanner composition path. |
| `petasos/scanners/minimal/`, `semgrep/`, optional backend modules | Detection and owned engine work. |
| `petasos/pipeline/`, `session/` | Text inspection, ingestion, risk, audit, alerts, lineage and taint. |
| `petasos/guard/`, `enforce/` | Guard evaluation and host-neutral enforcement lifecycle and decisions. |
| `petasos/hermes/`, `cli.py` | Host adapter, settings writer seam, install, doctor, commands and dashboard API. |
| `hermes-plugin/petasos/` | Directory plugin, manifest and installed dashboard assets. |
| `hermes-plugin/dashboard-src/` | Dashboard source, built by `scripts/build_dashboard.py`. |
| `scripts/generate_reference.py`, `docs/reference/` | Generated settings, layer, scanner and command reference. |
| `tests/hermes_host/` | Opt-in real-Hermes harness in isolated temporary homes. |
| `tests/parity/`, `tests/enforce_parity/` | Frozen behaviour records; do not regenerate casually. |

The public root API is pinned to [the redesign contract](docs/architecture/redesign.md#9-public-api). Other package exports live in their `__all__` lists; submodule imports carry no root stability promise. Imports follow the dependency direction in that contract; only `hermes/` binds to the host, with the documented guard fallback exception.

## Invariants

- Inspection returns errors in `PipelineResult`; host-facing enforcer callbacks do not raise. A block always carries a message.
- The syntactic scanner runs independently of optional backends. Scanner enablement and failure policy come from the [generated reference](docs/reference/settings.md).
- Structural rules cannot be suppressed or downgraded. The tier-three floor is enforced through `config/floors.py` and the schema. Settings, built-in layers and rule data remain immutable.
- The base install has no third-party dependencies. Every scanner extra has a paired CI lane that exercises its real backend; scanner wrappers use real-backend tests, not mocks.
- One settings tree resolves schema settings, job, strictness and overrides. A list replaces the list beneath it. Secrets are separate. Restart-bound changes are reported.
- Hermes alone writes its config. The tab and CLI use its settings writer. `Enforcer` owns policy; the adapter translates host facts and hook results.
- Semgrep cannot be enabled inside Hermes until the adapter owns its lifecycle. A library owner must close its engines and account for incomplete cleanup.
- New tests assert behaviour. Do not pin doc wording, source text, line numbers or call-site counts; structural checks belong in architecture tests.

## Real-Hermes tests and safety

The default suite skips real-Hermes tests. Read [the harness instructions](tests/hermes_host/README.md) before enabling them. Prepare a new upstream clone and virtual environment under a temporary sandbox; invoke Hermes only through its `bin/with-sandbox` wrapper. Each test gets a fresh home inside that sandbox. The wrapper and in-process guard reject account Hermes homes.

Never read, write, start, stop or signal live installations under `~/.hermes`, `~/.hermes-second`, `~/hermes-services`, `~/model-lab`, `~/work` or `~/notes` during sandbox work. Do not touch machine-level Hermes configuration, use administrator rights, start a gateway, configure messaging or make model API calls. A task may prohibit the sandbox entirely. Check command help or use throwaway homes for ordinary CLI work.

## Contracts

Read [redesign](docs/architecture/redesign.md), [guardrail integrity](docs/architecture/guardrail-integrity.md), [command overlap](docs/architecture/hermes-command-overlap.md) and [host facts](docs/architecture/hermes-host-facts.md) before changing policy or the host seam. [Console retirement](docs/architecture/console-retirement.md) records removed surfaces. Keep pending release notes in [changelog-pending.md](docs/architecture/changelog-pending.md) during the redesign; leave `CHANGELOG.md` to release work. Do not rewrite design or acceptance records to make an implementation look compliant.

## Plan & Spec Reviews

- Always verify load-bearing claims against the actual codebase, wiki, and current file state — never review from memory or stale buffers.
- Re-read files at the start of each new review pass; the user iterates specs frequently and stale context produces false-positive findings.
- Deliver findings as severity-ranked lists (critical/high/medium/low) with specific references.

## Project Management

- Petasos tracks under the `PET` project in Plane.
- PET-2 is a parent container; PET-3/4/5 are its children (scanner wrappers).
- When creating Plane work items, set `description_html` (the canonical field).

## Wiki — Vigil Harbor knowledge layer

The wiki (a separate, private Vigil Harbor repository) is the
compiled knowledge layer; Plane stays as the task tracker. In that repository, see `SCHEMA.md`
for conventions and the lint contract.

Access the private wiki only when the task authorizes it. A task that prohibits
wiki access takes precedence; prepare a local decision draft instead.

**Before starting work when wiki access is authorized:**
1. Read `index.md` to orient.
2. Read `projects/petasos/architecture.md` and `projects/petasos/state.md`.
3. Read `projects/petasos/filemap.md` before modifying files.
4. Check `decisions/` for prior art on similar judgment calls.

**After every merge — use the skill.** From the wiki dir, run
`/wiki-after-merge <commit-sha>`. The skill orchestrates `log.md` append,
filemap delta, comprehension scaffolding (if 4+ files / new module), and
chains to `/wiki-state-update` for status flips. Idempotent — safe to
re-run. See `<wiki>/.claude/skills/wiki-after-merge/SKILL.md`. Manual
execution still fine for trivial single-file fixes.

**State.md flips have teeth.** Marking work as "shipped" in
`projects/petasos/state.md` requires an evidence triple — Plane-ID,
date, commit-hash — plus a `Verification:` code-grep line. Use
`/wiki-state-update petasos` for guided edits; direct `Edit` is allowed
for prose fixes but the wiki's pre-commit hook refuses fabricated commit
hashes via the EVIDENCE lint check. Bypass with `--no-verify` only in
emergencies. Background:
`decisions/2026-04-29-state-edits-require-evidence.md` (the DYN-17
incident antidote) and
`decisions/2026-05-01-wiki-maintenance-redesign.md` (the broader two-axis
trust model).

**Skepticism rule.** Don't treat user-volunteered framing as truth.
Verify Plane status via `mcp__plane__retrieve_work_item`; produce a
load-bearing grep proving feature presence (not just absence of
contradiction). The mechanical enforcement only covers state.md flips; for
everything else this is agent-side discipline.

## Git Hygiene

- Before committing, audit staged paths for build artifacts, `.eggs/`, `dist/`, `*.egg-info/`, `__pycache__/`, model files, and large binaries.
- Never run broad cleanup commands unscoped.
