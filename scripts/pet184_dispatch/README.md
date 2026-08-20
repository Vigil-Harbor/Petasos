# pet184_dispatch

Dispatch runner for adversarial cross-model review of a Petasos release
surface (PET-184). It sends bounded review payloads to a non-Claude model,
persists whatever comes back verbatim, and classifies each dispatch against a
total rule set so that "no findings" and "never actually read" can never look
alike.

**This is an internal ops tool. It is not part of the published `petasos`
package.** `pyproject.toml` declares no `[tool.hatch.build]` section, so
hatchling packages `petasos/` only and nothing here reaches PyPI. It carries no
"runs on any deployment" obligation. See the MACHINE DEPENDENCIES block at the
top of `dispatch.ps1` for the full list of things it is pinned to.

## Why this is committed

The mechanics used to live in spec prose. Four review rounds showed that prose
patches closed their own target and then broke the mechanism beside them; one
round found eight such seams and none in anything older. Moving the mechanics
into code with an executable self-test stopped that, because a self-test can
check a marker schema, a meta schema, and a manifest join key against each
other, and prose review cannot.

It lives here rather than beside its output so the tool survives cleanup of any
one review run.

## The tool / run split

The tool is tracked. Its output is not. The two live in different places on
purpose, and the runner refuses to blur them.

| Travels with the tool (tracked) | Belongs to a run (gitignored) |
| --- | --- |
| `dispatch.ps1` | `raw/`, raw reviewer output |
| `marker.schema.json` | `prompts/`, prompt copies |
| `meta.schema.json` | `attempts.json`, the retry ledger |
| `attempts.schema.json` | `coverage_map.json` |
| `validate.py` | `report.md` |
| `schema.json` (canonical reviewer contract) | `schema.json` (the run's copy, hashed at step 0b) |

`schema.json` appears on both sides deliberately. The copy here is canonical.
Design step 0b copies it into the run directory and records its SHA-256; a real
dispatch then reads the run's copy through `-ReportDir`.

`-ReportDir` is **required** for any real dispatch. It has no default, because a
default would resolve to this tracked directory and write run artifacts into the
repository.

## Running it

The self-test exercises every mechanic against stubs. It needs no `codex`
authentication, no LM Studio, and no network.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\pet184_dispatch\dispatch.ps1 -SelfTest
```

Expect a closing `CHECKS: passed=N failed=0 skipped=0` line and exit 0. **A skip
is a failure here.** The gate exits 1 on any skip, because skips in this suite
come from environmental noise such as a busy port or a transient file lock, and
a leg that did not run must never read as green. Re-run rather than accepting
one. The suite writes its fixtures to `$env:TEMP` and leaves the working tree
untouched.

Dot-sourcing loads the functions without running anything:

```powershell
. .\scripts\pet184_dispatch\dispatch.ps1
Resolve-FallbackTarget -Target (Get-FallbackTargets)[0]
```

Dot-sourcing does not mutate the caller's StrictMode or `$ErrorActionPreference`.

## What the runner owns

Two dispatch kinds behind one contract, both writing the same four-file stem
plus an in-flight marker:

- `codex`: `node <codex.js> exec ... -o <stem>.json`, the primary reviewer.
- `http`: `POST {base_url}/chat/completions`, the fallback.

Also owned here rather than in prose: fallback target resolution (credential,
warm-up, byte ceiling, deadline probe), deadline scaling, the retry ledger, the
marker lifecycle, resume resolution, and the dispatch classifier.

A fallback target is a **model endpoint**, not a Hermes profile. Earlier
revisions named targets after the profiles whose config supplied a base URL and
a model ID, which coupled the review's reproducibility to unrelated profiles:
retuning one profile's model would have silently changed which model reviews the
release. Targets are now named for what they are. Hermes profile paths survive
only as the filesystem location of an API key file.

## Still owned by prose

`manifest.py` is unwritten; its enumeration rules are specified in the spec.
Payload assembly, splits and byte accounting, Plane filing, the orchestrator
side kill record, and evidence-quote resolution are human-executed. The
boundary table in the spec's `## The runner` section is authoritative.
