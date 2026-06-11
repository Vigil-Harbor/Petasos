# Deploying Petasos on Hermes Desktop

How to go from `pip install petasos` (zero enforcement) to a locked-down
Hermes Desktop agent. Covers both macOS and Windows.

**Hermes version:** v0.15.0+ (v0.16.0+ recommended — profile-aware)  
**Petasos version:** 0.1.0+  
**Time:** ~15 minutes (plus ML model download on first scan)

---

## 1. Install

Install Petasos into Hermes's Python environment — not system Python, not
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
`all` extra. This adds ~300MB of models. The plugin degrades gracefully
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

**LlamaFirewall prerequisite:** The LlamaFirewall backend requires a
Hugging Face token (`HF_TOKEN` env var) with access to
`meta-llama/Prompt-Guard-86M`. Set `HF_TOKEN` in your shell or `.env`
before first use, or the scanner will fail to load its model.

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
# Session secret (HMAC session binding — prevents session spoofing)
python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"

# Hash key (PII anonymization — HMAC key for correlatable hashing)
python -c "import secrets; print(secrets.token_hex(32))"
```

License activation is optional — for supporter/compliance recognition only.
Features are not gated by it. If you have an Ed25519 private key
(paired with `petasos/session/_keys/public.pem`):

```python
import jwt, time
from pathlib import Path

private_key = Path("tests/fixtures/test_private.pem").read_bytes()
now = int(time.time())
token = jwt.encode({
    "sub": "your-agent-id",
    "customer_id": "your-org",
    "tier": "enterprise",
    "features": ["frequency", "escalation", "tool_guard", "audit", "alerting"],
    "iat": now,
    "exp": now + (365 * 24 * 3600),
}, private_key, algorithm="EdDSA")
print(token)
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

**Override:** If `HERMES_HOME` is set, the `.env` file is at
`$HERMES_HOME/.env`.

```bash
PETASOS_SESSION_SECRET=<base64 output>
PETASOS_HASH_KEY=<hex output>
# PETASOS_LICENSE_KEY is optional — supporter/compliance recognition only
```

These match `*_KEY` / `*_SECRET` patterns so Hermes automatically strips
them from terminal subprocess environments (no credential leakage into
agent-executed commands).

## 3. Create the plugin

Petasos integrates via Hermes's plugin hook system — not shell hooks, not
a code fork. The plugin runs in-process with zero subprocess overhead.

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
description: "Content security pipeline — tool call guard, content scanning, audit"
hooks:
  - pre_tool_call
  - post_tool_call
  - on_session_start
```

### `__init__.py`

The reference implementation is maintained at
[`docs/deployment/reference_plugin/`](reference_plugin/) in this repo.

Key architectural decisions in the plugin:

- **Lazy init.** Scanners load in a background thread. The plugin
  registers hooks and returns immediately so Hermes Desktop doesn't
  stall on ML model cold-start. Early tool calls during init use
  MinimalScanner-only (17 regex rules, <1ms).

- **Async bridge.** `ToolCallGuard.evaluate()` is async (it calls
  `Pipeline.inspect()` for param scanning). Hermes's `invoke_hook()`
  is sync. The plugin runs a dedicated asyncio event loop in a daemon
  thread and bridges with `run_coroutine_threadsafe().result()`.

- **Inverted tool coverage.** Instead of enumerating dangerous tools
  (incomplete — there are 70+), maintain a `READ_ONLY_TOOLS` frozenset.
  Everything not in that set is treated as dangerous for
  `param_scan_unsafe` enforcement.

- **Graceful degradation.** Missing `PETASOS_SESSION_SECRET` → HMAC
  binding disabled. Missing config section → defaults apply (all
  features enabled as of PET-78). Plugin never crashes Hermes.

- **Profile-aware config resolution.** The plugin uses
  `resolve_hermes_config_path()` to find config.yaml across
  `HERMES_HOME` → active profile → v0.15 root. Both the agent plugin
  and the dashboard plugin share this resolver so they always read the
  same file (no split-brain).

## 4. Enable the plugin

Hermes's plugin loader requires explicit opt-in. Add a `plugins:` section
to `config.yaml`:

```yaml
plugins:
  enabled:
    - petasos
```

**This step is easy to miss.** Without it, the plugin is discovered but
skipped: `Skipping 'petasos' (not in plugins.enabled)` in the agent log.

## 5. Configure

Add a top-level `petasos:` section to `config.yaml`. This key survives
Desktop UI model switches (the UI only rewrites the `model:` section).

**Important:** On v0.16+, edit the **profile's** `config.yaml`, not the
root one. If your active profile is `gibson`:

```text
# macOS:   ~/.hermes/profiles/gibson/config.yaml
# Windows: %LOCALAPPDATA%\hermes\profiles\gibson\config.yaml
```

```yaml
petasos:
  enabled: true
  fail_mode: "closed"
  host_id: "your-agent-id"

  # Normalization (all default true — listed for visibility)
  normalize_nfkc: true
  strip_zero_width: true
  map_homoglyphs: true
  detect_rtl_override: true

  # PII anonymization
  anonymize: true
  pii_entities: ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD"]
  redaction_mode: "hash"

  # Session features (all default true — no license required)
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
| `fail_mode` | `"degraded"` | `"closed"` | Degraded is too permissive — blocks on total ML failure but passes on partial |
| `host_id` | `""` | Set to stable ID | HMAC session binding requires non-empty host_id. Changing it invalidates all session tokens |
| `anonymize` | `false` | `true` | PII detection + hash anonymization for audit correlation |

### What stays at defaults

| Key | Default | Why it's fine |
|-----|---------|---------------|
| `frequency_enabled` | `true` | Enabled out of the box |
| `tool_guard_enabled` | `true` | Enabled out of the box |
| `audit_enabled` | `true` | Enabled out of the box |
| `scanner_timeout_seconds` | 10.0 | Generous for cold-start, capped at 60 |
| `tier1_threshold` / `tier2_threshold` | 15.0 / 30.0 | Battle-tested from Drawbridge |
| `tier3_threshold` | 50.0 | Floor hardcoded at 30.0 — can't go lower |
| `session_ttl_seconds` | 3600.0 | 1-hour TTL matches typical chat session |
| Normalization toggles | all `true` | No reason to disable any |

## 6. Restart and verify

**Full app restart required.** Plugin discovery runs at app startup, not
per-session. Closing a chat tab and opening a new one is not enough —
close Hermes Desktop entirely and reopen.

Check `agent.log` for the initialization sequence:

```text
INFO  petasos.plugin: loading config from %LOCALAPPDATA%\hermes\profiles\gibson\config.yaml [tier=profile]
INFO  petasos.plugin: Petasos plugin registered — hooks active, scanner init in background
INFO  petasos.plugin: LLM Guard scanner loaded
INFO  petasos.plugin: LlamaFirewall scanner loaded
INFO  petasos.plugin: Presidio scanner loaded
INFO  petasos.plugin: Petasos initialized: scanners=['minimal', 'llm_guard', ...], fail_mode=closed, host_id=...
INFO  petasos.plugin: PETASOS_SESSION_START — Petasos content security active
```

The new `loading config from ... [tier=...]` line confirms which config
file the plugin resolved to. If it says `[tier=root]` when you expected
`[tier=profile]`, check that `active_profile` contains your profile name.

### Dashboard backend routes

Backend API routes (`/api/plugins/petasos/*`) mount only at dashboard
startup. The `/api/dashboard/plugins/rescan` endpoint refreshes the tab
list only — it does **not** reload plugin backend routes. If you add or
update the plugin, restart the dashboard process to mount the new routes.
(Observed 2026-06-09.)

### Gateway restart

**Caution:** The `/api/gateway/restart` endpoint can hang on an
interactive "install service [Y/n]" prompt if no system service is
configured, leaving the gateway **stopped**. (Observed 2026-06-09 and
2026-06-10.)

**Safe restart procedure:**

1. Stop the gateway via the dashboard API or process manager
2. Launch a detached `hermes gateway` process manually
3. Verify the gateway is responding

Do not rely on the restart API unless you have confirmed the service
unit is pre-installed.

### Verification script

A standalone verification script (`verify.py` in the reference plugin
directory) checks all components including split-brain detection:

**macOS:**

```bash
~/.hermes/hermes-agent/venv/bin/python plugins/petasos/verify.py
```

**Windows (PowerShell / cmd):**

```powershell
%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe plugins/petasos/verify.py
```

Expected output: checks for scanner imports, plugin files, config
validation, env vars, injection detection, and config split-brain — all
PASS. The header line shows which config file was resolved and the
winning tier.

### Upgrading Hermes orphans plugins

Hermes v0.16+ config migration copies config keys (including `petasos:`)
into the new profile home, but it does **not** copy plugin files. After a
Hermes major or minor update:

1. Check the new `loading config from ...` INFO line — confirm it points
   to the profile config, not the root.
2. If `check_plugin_files` FAILs in `verify.py`, copy the plugin
   directory to the profile home:

   ```bash
   # macOS (profile = gibson)
   cp -r ~/.hermes/plugins/petasos ~/.hermes/profiles/gibson/plugins/petasos

   # Windows (PowerShell)
   Copy-Item -Recurse "$env:LOCALAPPDATA\hermes\plugins\petasos" "$env:LOCALAPPDATA\hermes\profiles\gibson\plugins\petasos"
   ```

3. Restart Hermes Desktop.

If the plugin files are absent from the resolved home, enforcement is
**silently off** — no error, no log warning (the plugin simply isn't
discovered). The `verify.py` script and the `loading config from ...`
INFO line are the primary diagnostic tools.

## 7. What's enforced

When a tool call arrives at `pre_tool_call`:

| Condition | Action | Log marker |
|-----------|--------|------------|
| `allowed=False` | Block, return reason to model | `PETASOS_BLOCK` |
| `allowed=True`, `param_scan_unsafe=True`, non-read-only tool | Block | `PETASOS_QUARANTINE` |
| `allowed=True`, HIGH/CRITICAL findings, non-read-only tool | Block | `PETASOS_QUARANTINE` |
| `tier == "tier3"` | Block all subsequent calls for session | `PETASOS_TIER3` |
| `allowed=True`, clean or read-only tool | Allow | (no log) |

The guard scans tool **parameters** through the full pipeline (normalize →
syntactic pre-filter → ML fan-out → merge → fail-mode). This catches
injection payloads smuggled via tool arguments, not just chat messages.

## Platform notes

### macOS

Straightforward. System shell, native Python, no translation layers.

`~/.hermes` is the current macOS root. If a future Hermes release
relocates it (e.g., `~/Library/Application Support`), the resolver and
this doc track Hermes — re-verify on Hermes major updates.

### Windows

- **No Git Bash overhead.** Plugin hooks run in-process, not as
  subprocesses. The 100-200ms MINGW64 overhead that affects shell hooks
  does not apply.
- **Python path.** Use Hermes's bundled venv, not system/WSL Python.
  Wrong Python → scanner imports fail silently.
- **Config paths.** v0.16+: `%LOCALAPPDATA%\hermes\profiles\<active>\config.yaml`
  and `.env`. v0.15: `%LOCALAPPDATA%\hermes\config.yaml` and `.env`.
- **`HERMES_HOME` override.** If set, all config and plugin paths
  resolve relative to `$HERMES_HOME` regardless of profile state.
- **Credential env var isolation.** `PETASOS_*` vars matching
  `*_KEY`/`*_SECRET` patterns are auto-stripped from terminal subprocess
  env by `_build_provider_env_blocklist()`.

## Troubleshooting

### Plugin not loading

Check `agent.log` for `Skipping 'petasos'`:

- `"not in plugins.enabled"` → Add `plugins: enabled: [petasos]` to
  config.yaml.
- `"exclusive plugin"` → Your `__init__.py` contains `MemoryProvider` or
  `register_memory_provider` strings. Remove them.
- No mention of petasos at all → `plugin.yaml` missing or in wrong
  directory. On v0.16+ check the **profile** plugins directory, not
  root. Run `verify.py` to confirm the resolved path.

### Scanner import failures

```text
INFO petasos.plugin: LLM Guard not installed — syntactic-only for that backend
```

This is graceful degradation, not an error. Install `petasos[all]` in
Hermes's venv for ML backends. The syntactic pre-filter (17 regex rules)
still runs without ML.

### License invalid

```text
WARNING petasos.plugin: Petasos license invalid (state=LicenseState.EXPIRED)
```

License is optional — features are not gated by it. If you want
supporter/compliance recognition, mint a new JWT. Check that
`PETASOS_LICENSE_KEY` in `.env` has no trailing whitespace or newlines.

### Config section wiped

The `petasos:` section is a top-level key — it survives UI model switches.
If it disappears, check for concurrent config.yaml editors or a Hermes
update that overwrote the file.

### Config split-brain

If `verify.py` reports `Config split-brain`, the root and profile
`petasos:` sections have divergent values. The profile config is the one
the running processes use — update the root config to match, or remove
the root's `petasos:` section to eliminate the drift.

### ToolCallGuard constructor error

```text
ERROR petasos.plugin: ToolCallGuard.__init__() missing 2 required positional arguments
```

ToolCallGuard requires `(pipeline, frequency_tracker, config)`. If using
the reference plugin, this is wired automatically. If writing custom
integration, construct a `FrequencyTracker(config)` and pass it.

### Model confabulates about blocked commands

The model may claim a blocked command "ran but produced no output."
This is a model behavior issue, not a Petasos issue. Improve the block
message to include `[BLOCKED]` and `was NOT executed` so the model
reports accurately. See GAV-5.
