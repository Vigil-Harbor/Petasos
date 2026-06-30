# Deploying Petasos on Hermes Desktop

How to go from `pip install petasos` (zero enforcement) to a locked-down
Hermes Desktop agent. Covers both macOS and Windows.

> **Before you start:** read the [deployment hardening checklist](hardening.md)
> for where Petasos sits in your security model. It is a detection layer, not a
> boundary; the checklist covers console binding, secrets, fail-mode, and the
> OS-level isolation to pair it with.

**Hermes version:** v0.15.0+ (v0.16.0+ recommended, profile-aware)  
**Petasos version:** 0.1.0+  
**Time:** about 15 minutes, plus the ML model download on first scan

---

## 1. Install

Install Petasos into Hermes's Python environment, not system Python and not
WSL Python. On Windows the venv lives inside the Hermes install directory.

**macOS:**

```bash
~/.hermes/hermes-agent/venv/bin/pip install petasos
```

**Windows (PowerShell / cmd):**

```powershell
%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe -m pip install petasos
```

**Windows (Git Bash):**

```bash
/c/Users/$USER/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe -m pip install petasos
```

For ML scanner backends (LLM Guard, LlamaFirewall, Presidio), install the
`all` extra. This adds about 300MB of models. The plugin degrades gracefully
to syntactic-only if these aren't installed.

**macOS:**

```bash
~/.hermes/hermes-agent/venv/bin/pip install "petasos[all]"
```

**Windows (PowerShell / cmd):**

```powershell
%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe -m pip install "petasos[all]"
```

**Windows (Git Bash):**

```bash
/c/Users/$USER/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe -m pip install "petasos[all]"
```

**LlamaFirewall prerequisite:** the LlamaFirewall backend needs a Hugging Face
token (`HF_TOKEN`) with access to the gated `meta-llama/Llama-Prompt-Guard-2-86M`
model. Accept the model license and set `HF_TOKEN` before first use, or the
scanner fails to load. Full steps are in
[PromptGuard model prerequisites](#promptguard-model-prerequisites) below.

Verify the install:

**macOS:**

```bash
~/.hermes/hermes-agent/venv/bin/python -c "from petasos import Pipeline; from petasos.scanners import MinimalScanner; print('OK')"
```

**Windows (PowerShell / cmd):**

```powershell
%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe -c "from petasos import Pipeline; from petasos.scanners import MinimalScanner; print('OK')"
```

## 2. Generate credentials

Two env vars, generated once per deployment.

```bash
# Session secret (HMAC session binding, prevents session spoofing)
python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"

# Hash key (PII anonymization, HMAC key for correlatable hashing)
python -c "import secrets; print(secrets.token_hex(32))"
```

Add credentials to Hermes's `.env` file.

**v0.16+ (profile-aware):** `.env` lives under the active profile home.
If your active profile is `gibson`:

```text
# macOS:   ~/.hermes/profiles/gibson/.env
# Windows: %LOCALAPPDATA%\hermes\profiles\gibson\.env
```

**v0.15 / default profile:**

```text
# macOS:   ~/.hermes/.env
# Windows: %LOCALAPPDATA%\hermes\.env
```

**Override:** if `HERMES_HOME` is set, the `.env` file is at `$HERMES_HOME/.env`.

```bash
PETASOS_SESSION_SECRET=<base64 output>
PETASOS_HASH_KEY=<hex output>
```

These match `*_KEY` / `*_SECRET` patterns, so Hermes automatically strips them
from terminal subprocess environments (no credential leakage into
agent-executed commands).

> **License is optional and gates nothing.** Every feature ships free. The
> `PETASOS_LICENSE_KEY` env var exists only for future supporter or compliance
> recognition, so leave it unset unless you have been given one.

## 3. Create the plugin

Petasos integrates via Hermes's plugin hook system, not shell hooks and not a
code fork. The plugin runs in-process with zero subprocess overhead.

Create the plugin directory in the active Hermes home:

**v0.16+ (profile-aware):**

```text
# macOS   (profile = gibson)
~/.hermes/profiles/gibson/plugins/petasos/

# Windows (profile = gibson)
%LOCALAPPDATA%\hermes\profiles\gibson\plugins\petasos\
```

**v0.15 / default profile:**

```text
# macOS
~/.hermes/plugins/petasos/

# Windows
%LOCALAPPDATA%\hermes\plugins\petasos\
```

Two files required:

### `plugin.yaml`

```yaml
name: petasos
version: 1.0.0
description: "Content security pipeline: tool call guard, content scanning, audit"
hooks:
  - pre_tool_call
  - post_tool_call
  - on_session_start
  # Sub-agent (delegate_task) session hooks, optional: extend escalation across
  # delegated sub-agents and cap delegation fan-out. Safe to register even if
  # the host build does not emit them (the lineage half simply no-ops).
  - subagent_start
  - subagent_stop
```

### Sub-agent (delegate_task) session intelligence

A Hermes `delegate_task` spawns a child agent with its own fresh `session_id`.
Without extra wiring, a session escalating toward tier 2/3 could launder its
risk through a clean child, and a parent's tier-3 termination would never reach
its children. Registering the sub-agent hooks closes both gaps:

- **Lineage-linked escalation.** A child inherits the highest tier in its parent
  chain, read live, so a parent at tier 3 forces its children to tier 3 on their
  *next* guarded tool call (the hook model cannot interrupt an in-flight call).
  Needs `subagent_start` / `subagent_stop`.
- **Delegation fan-out cap.** An escalation-tied budget on `delegate_task` spawns
  (tunable via `delegate_max_fanout_per_window`, `delegate_fanout_window_seconds`,
  and `delegate_tool_names`) stops a high-frequency session from spraying
  sub-agents. Needs only `pre_tool_call`, so it runs even when the sub-agent
  hooks are unavailable.

Both default on. If the host does not emit the sub-agent hooks, lineage
escalation no-ops and only the fan-out cap runs (logged once at startup).

### `__init__.py`

The reference implementation is maintained at
[`docs/deployment/reference_plugin/`](reference_plugin/) in this repo. Key
behaviors to preserve in any custom integration:

- **Lazy init.** Scanners load in a background thread. The plugin registers
  hooks and returns immediately so Hermes Desktop doesn't stall on ML model
  cold-start. Early tool calls during init use MinimalScanner only (23 regex
  rules, under 5ms).
- **Async bridge.** `ToolCallGuard.evaluate()` is async (it calls
  `Pipeline.inspect()` for param scanning); Hermes's `invoke_hook()` is sync.
  The plugin runs a dedicated asyncio event loop in a daemon thread and bridges
  with `run_coroutine_threadsafe().result()`.
- **Inverted tool coverage.** Instead of enumerating dangerous tools
  (incomplete, there are 70+), maintain a `READ_ONLY_TOOLS` frozenset.
  Everything not in that set is treated as dangerous for `param_scan_unsafe`
  enforcement.
- **Graceful degradation.** Missing `PETASOS_SESSION_SECRET` disables HMAC
  binding; a missing config section falls back to defaults (all features
  enabled). The plugin never crashes Hermes.
- **Profile-aware config resolution.** The plugin uses
  `resolve_hermes_config_path()` to find `config.yaml` across `HERMES_HOME`,
  then the active profile, then the v0.15 root. The agent plugin and the
  dashboard plugin share this resolver so they always read the same file (no
  split-brain).

## 4. Enable the plugin

Hermes's plugin loader requires explicit opt-in. Add a `plugins:` section to
`config.yaml`:

```yaml
plugins:
  enabled:
    - petasos
```

**This step is easy to miss.** Without it, the plugin is discovered but
skipped: `Skipping 'petasos' (not in plugins.enabled)` in the agent log.

## 5. Configure

Add a top-level `petasos:` section to `config.yaml`. This key survives Desktop
UI model switches (the UI only rewrites the `model:` section).

To configure several agent roles from one install, use the Config Editor's
Hermes-agent-profile selector instead of hand-editing each file: see
[Per-Hermes-agent security profiles](../usage/hermes-agent-profiles.md).

**Important:** on v0.16+, edit the **profile's** `config.yaml`, not the root
one. If your active profile is `gibson`:

```text
# macOS:   ~/.hermes/profiles/gibson/config.yaml
# Windows: %LOCALAPPDATA%\hermes\profiles\gibson\config.yaml
```

```yaml
petasos:
  enabled: true
  fail_mode: "closed"
  host_id: "your-agent-id"

  # Normalization (all default true, listed for visibility)
  normalize_nfkc: true
  strip_zero_width: true
  map_homoglyphs: true
  detect_rtl_override: true

  # PII anonymization
  anonymize: true
  pii_entities: ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD"]
  redaction_mode: "hash"

  # Session features (all default true, no license required)
  frequency_enabled: true
  escalation_enabled: true
  tool_guard_enabled: true
  audit_enabled: true
  alert_enabled: true
  audit_verbosity: "standard"
```

### Config reference

| Key | Default | Production | Why |
|-----|---------|------------|-----|
| `fail_mode` | `"degraded"` | `"closed"` | Degraded is too permissive: it blocks on total ML failure but passes on partial |
| `host_id` | `""` | Set to a stable ID | HMAC session binding needs a non-empty `host_id`; changing it invalidates all session tokens |
| `anonymize` | `false` | `true` | PII detection plus hash anonymization for audit correlation |

### What stays at defaults

| Key | Default | Why it's fine |
|-----|---------|---------------|
| `frequency_enabled` | `true` | Enabled out of the box |
| `tool_guard_enabled` | `true` | Enabled out of the box |
| `audit_enabled` | `true` | Enabled out of the box |
| `scanner_timeout_seconds` | 10.0 | Generous for cold-start, capped at 60 |
| `tier1_threshold` / `tier2_threshold` | 15.0 / 30.0 | Tuned defaults carried over from [Drawbridge](https://github.com/ziomancer/clawmoat-drawbridge) (prior art) |
| `tier3_threshold` | 50.0 | Floor hardcoded at 30.0, cannot go lower |
| `session_ttl_seconds` | 3600.0 | 1-hour TTL matches a typical chat session |
| Normalization toggles | all `true` | No reason to disable any |

### Tool-name canonicalization vs Hermes dispatch

The `pre_tool_call` hook (where the guard runs) sees the **raw model-emitted
tool name**. Hermes resolves that raw name to a registered tool *after* the hook
fires, trying a candidate set (lowercase, separator-normalized, CamelCase to
snake, `_tool` / `-tool` suffix-stripped) and finally a fuzzy (`difflib`)
fallback. Petasos canonicalizes both your configured names and the incoming name
through one shared function, so a `SendEmail` / `SEND_EMAIL` / `send_email_tool`
variant of a configured egress tool is still matched. Two operator-facing
consequences:

- **List MCP tools by their full single-underscore wire name.** Hermes
  namespaces MCP tools as `mcp_<server>_<tool>` (for example
  `mcp_acme_send_email`), where `_` is *both* the separator and a legal
  character inside server and tool names, so the boundary is not recoverable
  without the registry. Petasos therefore does **not** heuristically strip the
  single-underscore `mcp_` prefix (a greedy strip would mis-segment real names
  and add false matches). Use the **full wire name** wherever you name the tool.
  Note these are two separate mechanisms, not two config steps:
  `egress_sink_tools` is an operator knob in `config.yaml` (below), while the
  read-only set is *code* (the plugin's `READ_ONLY_TOOLS` constant,
  canonicalized at load into `_READ_ONLY_CANON`, which `_is_dangerous()`
  consults directly). Customize the read-only set by editing the plugin, not
  `config.yaml`.

  ```yaml
  # Right: full single-underscore wire name; its case / CamelCase / _tool
  #        variants all canonicalize onto this entry.
  egress_sink_tools:
    - mcp_acme_send_email
  # Wrong: bare name; the namespaced wire name will NOT match it.
  #   - send_email
  ```

  (The double-underscore `mcp__<server>__` / `hermes__` prefix *is* stripped:
  that is the OpenClaw / Claude-Code convention, harmless but inert for Hermes.)

- **Bound or disable Hermes's fuzzy fallback host-side.** Hermes's
  `difflib.get_close_matches(..., cutoff=0.7)` last resort can map a name no
  deterministic canonicalizer can reproduce (for example `snd_eml` to
  `send_email`). Petasos deliberately does **not** mirror fuzzy resolution. If
  your Hermes build allows it, bound or disable the fuzzy tool-name fallback so a
  fuzzily-resolved variant cannot reach a real egress or dangerous tool without
  an exact, deterministic match the guard also sees.

## 6. Restart and verify

**Full app restart required.** Plugin discovery runs at app startup, not
per-session. Closing a chat tab and opening a new one is not enough: close
Hermes Desktop entirely and reopen.

Check `agent.log` for the initialization sequence:

```text
INFO  petasos.plugin: loading config from %LOCALAPPDATA%\hermes\profiles\gibson\config.yaml [tier=profile]
INFO  petasos.plugin: Petasos plugin registered, hooks active, scanner init in background
INFO  petasos.plugin: LLM Guard backend verified, scanner active
INFO  petasos.plugin: LlamaFirewall backend verified, scanner active
INFO  petasos.plugin: Presidio backend verified, scanner active
INFO  petasos.plugin: Petasos initialized: scanners=['minimal', 'llm_guard', ...], unavailable=[], fail_mode=closed, host_id=...
INFO  petasos.plugin: PETASOS_SESSION_START, Petasos content security active
```

If a backend is not installed, you will see `backend missing` instead of
`backend verified`.

The `loading config from ... [tier=...]` line confirms which config file the
plugin resolved to. If it says `[tier=root]` when you expected `[tier=profile]`,
check that `active_profile` contains your profile name.

### Dashboard backend routes

Backend API routes (`/api/plugins/petasos/*`) mount only at dashboard startup.
The `/api/dashboard/plugins/rescan` endpoint refreshes the tab list only; it
does **not** reload plugin backend routes. If you add or update the plugin,
restart the dashboard process to mount the new routes.

### Gateway restart

**Caution:** the `/api/gateway/restart` endpoint can hang on an interactive
"install service [Y/n]" prompt if no system service is configured, leaving the
gateway **stopped**. Safe restart procedure:

1. Stop the gateway via the dashboard API or process manager.
2. Launch a detached `hermes gateway` process manually.
3. Verify the gateway is responding.

Do not rely on the restart API unless you have confirmed the service unit is
pre-installed.

### Verification script

A standalone verification script (`verify.py` in the reference plugin directory)
checks all components, including split-brain detection:

**macOS:**

```bash
~/.hermes/hermes-agent/venv/bin/python plugins/petasos/verify.py
```

**Windows (PowerShell / cmd):**

```powershell
%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe plugins/petasos/verify.py
```

Expected output: checks for scanner imports, plugin files, config validation,
env vars, injection detection, and config split-brain, all PASS. The header line
shows which config file was resolved and the winning tier.

### Upgrading Hermes orphans plugins

After any Hermes update, three layers can drift independently, and Petasos only
enforces when all three line up. Re-check all three; a mismatch fails **silently**,
not loudly:

1. **The library** in Hermes's venv (`pip show petasos`). A venv rebuild can drop
   the wheel or its ML deps (see *Scanner import failures*).
2. **The plugin files** in the resolved profile home. Hermes migrates the
   `petasos:` config but never copies plugin files (this section).
3. **The processes** (gateway + dashboard). They pin config at boot, so an edit
   only takes effect after a restart (see *Restart and verify*).

Hermes v0.16+ config migration copies config keys (including `petasos:`) into the
new profile home, but it does **not** copy plugin files. After a Hermes major or
minor update:

1. Check the new `loading config from ...` INFO line; confirm it points to the
   profile config, not the root.
2. If `check_plugin_files` FAILs in `verify.py`, copy the plugin directory to the
   profile home:

   ```bash
   # macOS (profile = gibson)
   cp -r ~/.hermes/plugins/petasos ~/.hermes/profiles/gibson/plugins/petasos

   # Windows (PowerShell)
   Copy-Item -Recurse "$env:LOCALAPPDATA\hermes\plugins\petasos" "$env:LOCALAPPDATA\hermes\profiles\gibson\plugins\petasos"
   ```

3. Restart Hermes Desktop.

If the plugin files are absent from the resolved home, enforcement is **silently
off**: no error, no log warning (the plugin simply isn't discovered). The
`verify.py` script and the `loading config from ...` INFO line are the primary
diagnostic tools.

## Durable console backend across Hermes updates

The console backend (`config`, `scan`, `armed`, `scan-history`) can be served two
ways. Only one survives a Hermes host update without a manual re-drop. The in-tab
`9119` dashboard plugin mounts a backend only when Hermes treats it as a
**bundled** plugin, and a Hermes update rebuilds the install tree where that copy
lives, so the in-tab backend silently goes dark on each update. The durable answer
is to run the console as its own supervised process.

**Mount-verification (in-tab backend).** To confirm whether the in-tab `9119`
backend is actually mounted, read the `has_api` flag in `/api/dashboard/plugins`,
or send an **authenticated** health probe. A bare `401` from an unauthenticated
probe is NOT proof of mount: the dashboard auth middleware returns `401` whether
or not the route is mounted, so treat only `has_api: true` or an authenticated
non-`401`/non-`404` as confirmation.

<!-- PET-153-DURABLE-PATH -->
### Durable: supervised standalone console (recommended)

Run the console as its own OS-supervised process, decoupled from Hermes. Nothing
it depends on lives in the Hermes install tree, and the Hermes plugin-backend
mount policy is irrelevant to it, so a Hermes update cannot take it dark. This is
the shipped, durable path.

Petasos ships the entrypoint; the OS supervisor owns the lifecycle:

- **Entrypoint:** `petasos-console` (installed by the `console` extra) or the
  equivalent `python -m petasos.console`. It binds uvicorn to `127.0.0.1:8384` and
  serves a complete, self-contained UI and API on that one port. Open
  `http://127.0.0.1:8384` directly. The served UI is already a token-aware client
  (it takes the token in the UI, keeps it in `sessionStorage`, and sends it on
  every request and SSE call), so no rebuild is needed.
- **Install the extra** into the same interpreter the agent uses:
  `pip install "petasos[console]"`.
- **Supervisor:** register `petasos-console` under Windows Task Scheduler
  (mirroring the existing `Hermes_Gateway_<profile>` scheduled task) or macOS
  launchd. The supervisor restarts it on reboot and on crash. Petasos does not
  daemonize or supervise itself.

**Pin the agent's environment in the supervisor registration.** A Task Scheduler
or launchd process does not inherit the interactive agent's environment, so
without explicit pinning the supervised console can resolve a different profile's
`config.yaml` (and a different enforcement spool) than the agent enforces,
silently. Pin the same values the agent uses, in the Task Scheduler XML or launchd
plist:

- `HERMES_HOME` (or the active-profile context and the matching user account), so
  the console resolves the same config path the agent does.
- `PETASOS_SESSION_SECRET` and `PETASOS_HASH_KEY`, so the console reads the agent's
  HMAC-attested enforcement events as attested. Without the secret, session binding
  silently disables and attested events read as unattested.
- `PETASOS_CONSOLE_TOKEN` set to a **non-blank** value, so every `/api/*` data
  route requires `Authorization: Bearer <token>`. A set-but-blank value disables
  auth with one WARNING; do not register it blank.
- `PETASOS_LICENSE_KEY` if you use one.

**Auth posture.** When `PETASOS_CONSOLE_TOKEN` is a non-blank string, every
`/api/*` route returns `401` without a valid bearer token. The static page,
`/static`, and FastAPI's `/docs`, `/redoc`, and `/openapi.json` stay ungated; on a
localhost-only bind that is acceptable (the OpenAPI surface is a route map, not
scan data). This does not regress to an unauthenticated `127.0.0.1` surface.

**Startup self-check.** At startup the console logs the config line and one banner
at INFO immediately before binding:

```text
INFO petasos.dashboard: loading config from <path> [tier=<tier>]
INFO petasos.dashboard: petasos console starting: bind=127.0.0.1:8384 auth=on attestation=on
```

`auth` and `attestation` report **effective** state, not raw env presence:
`auth=off` means the token was unset or blank, and `attestation=off` means the
session secret did not decode. Compare the `loading config from` path against the
agent's own line to confirm both resolve the same profile. If the bind fails (port
already in use), the console logs an ERROR carrying the token
`PETASOS_CONSOLE_START_FAILED` and exits non-zero.

**Single-instance replacement.** Lifecycle and single-instance enforcement are the
supervisor's job. Before registering a new `petasos-console` task, stop and remove
any existing one; otherwise the stale instance can still hold `127.0.0.1:8384` and
the new one fails to bind (the same shape as the `Hermes_Gateway_<profile>`
PID-misidentification footgun). The port-in-use ERROR above makes the collision
self-diagnosing.

**Single-operator config writes.** With the standalone console running, two
processes can write `config.yaml` and the armed bit: the agent and the console
(via `PUT /api/config` and `POST /api/armed`). Each write is an atomic
read-modify-replace (no torn file), but two independent writers are
last-writer-wins with a lost-update window. Do not edit config from both the Hermes
tab and the standalone console at the same time.

<!-- PET-153-D2-FRAGILE: in-tree dashboard copy is wiped every Hermes update; not the durable path -->
### Interim only: in-tree bundled dashboard copy (fragile)

Before the supervised console is in place, the operator stopgap is a
dashboard-only bundled copy at `<hermes-agent>/plugins/petasos/dashboard/`, with
deliberately no root `plugin.yaml` or `__init__.py` so the dashboard discovery
mounts it as `bundled` (`has_api: true`) while the agent hook loader ignores it
(no double enforcement).

This works, but it lives inside the Hermes install tree that every Hermes update
rebuilds, so it is **wiped on each update** and the console silently goes dark
again. There is no documented durable bundled location and no relocation env, so
this copy cannot be made update-durable from the Petasos side. Treat it as a
stopgap that must be re-dropped after every Hermes update, and move to the
supervised standalone console above as the durable answer.

## PromptGuard model prerequisites

The LlamaFirewall PromptGuard component uses the gated Hugging Face model
`meta-llama/Llama-Prompt-Guard-2-86M`. To use it:

1. **Accept the license.** Visit
   [the model page](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M)
   and accept the Meta license from the Hugging Face account you will use.
2. **Set `HF_TOKEN`** for the gateway/dashboard process:
   ```bash
   export HF_TOKEN=hf_your_token_here
   ```
   Alternatively, place the token in `~/.cache/huggingface/token` or set
   `HF_TOKEN_PATH`.
3. **Or pre-download the model** on a machine with the token set:
   ```bash
   huggingface-cli download meta-llama/Llama-Prompt-Guard-2-86M
   ```
   The model is cached under `HF_HOME` (default `~/.cache/huggingface`).

If PromptGuard prerequisites are missing, Petasos fails fast with:

```text
PromptGuard model unavailable: set HF_TOKEN from a Hugging Face account
that has accepted the meta-llama/Llama-Prompt-Guard-2-86M license, or
pre-download the model; see docs/deployment/hermes-desktop.md
```

Petasos never prompts interactively for credentials: upstream's
`huggingface_hub.login()` stdin prompt is intercepted and converted to an
actionable error.

**Note:** install Petasos scanner extras while the gateway is stopped, or restart
after installing. A scan landing mid-`pip install` can latch a terminal load
error until restart.

## 7. What's enforced

When a tool call arrives at `pre_tool_call`:

| Condition | Action | Log marker |
|-----------|--------|------------|
| `allowed=False` | Block, return reason to model | `PETASOS_BLOCK` |
| `allowed=True`, `param_scan_unsafe=True`, non-read-only tool | Block | `PETASOS_QUARANTINE` |
| `allowed=True`, HIGH/CRITICAL findings, non-read-only tool | Block | `PETASOS_QUARANTINE` |
| `tier == "tier3"` | Block all subsequent calls for the session | `PETASOS_TIER3` |
| `allowed=True`, clean or read-only tool | Allow | (no log) |

The guard scans tool **parameters** through the full pipeline (normalize,
syntactic pre-filter, ML fan-out, merge, fail-mode). This catches injection
payloads smuggled via tool arguments, not just chat messages.

## Platform notes

### macOS

Straightforward: system shell, native Python, no translation layers.

`~/.hermes` is the current macOS root. If a future Hermes release relocates it
(for example to `~/Library/Application Support`), the resolver and this doc track
Hermes; re-verify on Hermes major updates.

### Windows

- **No Git Bash overhead.** Plugin hooks run in-process, not as subprocesses.
  The 100-200ms MINGW64 overhead that affects shell hooks does not apply.
- **Python path.** Use Hermes's bundled venv, not system or WSL Python. The
  wrong Python makes scanner imports fail silently.
- **Config paths.** v0.16+: `%LOCALAPPDATA%\hermes\profiles\<active>\config.yaml`
  and `.env`. v0.15: `%LOCALAPPDATA%\hermes\config.yaml` and `.env`.
- **`HERMES_HOME` override.** If set, all config and plugin paths resolve
  relative to `$HERMES_HOME` regardless of profile state.
- **Credential env var isolation.** `PETASOS_*` vars matching `*_KEY` / `*_SECRET`
  patterns are auto-stripped from terminal subprocess env by
  `_build_provider_env_blocklist()`.

## Troubleshooting

### Plugin not loading

Check `agent.log` for `Skipping 'petasos'`:

- `"not in plugins.enabled"`: add `plugins: enabled: [petasos]` to `config.yaml`.
- `"exclusive plugin"`: your `__init__.py` contains `MemoryProvider` or
  `register_memory_provider` strings. Remove them.
- No mention of petasos at all: `plugin.yaml` is missing or in the wrong
  directory. On v0.16+ check the **profile** plugins directory, not root. Run
  `verify.py` to confirm the resolved path.

### Scanner import failures

```text
INFO petasos.plugin: LLM Guard not installed, syntactic-only for that backend
```

This is graceful degradation, not an error. Install `petasos[all]` in Hermes's
venv for ML backends. The syntactic pre-filter (23 regex rules) still runs
without ML.

**Venv-rebuild dep loss (silent).** A Hermes venv rebuild can drop transitive
dependencies the ML backends import indirectly. The classic failure is a missing
`packaging`, which makes spaCy/thinc raise on import and takes Presidio and LLM
Guard down with it even though `petasos[all]` shows as installed. After any venv
rebuild, re-install `petasos[all]`, keep the JWT lib pinned at `pyjwt==2.12.1`
(the version the reference plugin expects), and confirm which backends actually
loaded from the plugin health endpoint (`/api/plugins/petasos/health`) rather
than assuming the install succeeded.

### License invalid

A `Petasos license invalid` warning is harmless: the license gates nothing and
every feature stays on. It only matters if you use the optional
`PETASOS_LICENSE_KEY` for supporter/compliance recognition, in which case check
that the value in `.env` has no trailing whitespace or newlines.

### Config section wiped

The `petasos:` section is a top-level key, so it survives UI model switches. If it
disappears, check for concurrent `config.yaml` editors or a Hermes update that
overwrote the file.

### Config split-brain

If `verify.py` reports `Config split-brain`, the root and profile `petasos:`
sections have divergent values. The profile config is the one the running
processes use: update the root config to match, or remove the root's `petasos:`
section to eliminate the drift.

### ToolCallGuard constructor error

```text
ERROR petasos.plugin: ToolCallGuard.__init__() missing 2 required positional arguments
```

`ToolCallGuard` requires `(pipeline, frequency_tracker, config)`. The reference
plugin wires this automatically. In a custom integration, construct a
`FrequencyTracker(config)` and pass it.

### Model claims a blocked command ran

The model may claim a blocked command "ran but produced no output." This is a
model-behavior issue, not a Petasos one. Make the block message explicit (include
`[BLOCKED]` and `was NOT executed`) so the model reports accurately.
