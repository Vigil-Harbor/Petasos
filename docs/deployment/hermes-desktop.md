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

For ML scanner backends (Presidio and PromptGuard), install the `all` extra and
then the spaCy model, which the extra does not include. Use the same Hermes
interpreter for both, so the model lands where Hermes can load it.

**macOS:**

```bash
~/.hermes/hermes-agent/venv/bin/pip install "petasos[all]"
~/.hermes/hermes-agent/venv/bin/python -m spacy download en_core_web_lg
```

**Windows (PowerShell / cmd):**

```powershell
%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe -m pip install "petasos[all]"
%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe -m spacy download en_core_web_lg
```

**Windows (Git Bash):**

```bash
/c/Users/$USER/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe -m pip install "petasos[all]"
/c/Users/$USER/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe -m spacy download en_core_web_lg
```

Measured on Windows with Python 3.14, that is about 1.2 GiB of packages including
the 425 MiB spaCy model, and it may be larger on Linux. The gated PromptGuard
weights add about 1.1 GB. A registered backend that is not installed does not
degrade gracefully: under `closed` or `degraded` it blocks all content until you
install it or list it in `disabled_scanners`. See
[Upgrading to the PromptGuard backend](#upgrading-to-the-promptguard-backend).

**Hermes generations without pip.** Install the plugin with `petasos hermes install`
and check it with `petasos doctor`. The Petasos tab in Hermes's dashboard shows
which scanners loaded.

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

**PromptGuard prerequisite:** the PromptGuard backend needs the gated
`meta-llama/Llama-Prompt-Guard-2-86M` model at a pinned revision. Accept the model
access terms, then pre-download it or make a token available before first use, or every
scan through the backend errors. Full steps are in
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

<!-- PET-170-MANIFEST-START -->
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
  # Ingestion-result scan seam, optional: scans what a read-only tool RETURNS
  # (file, web page, MCP record) and prefixes a warning banner when the content
  # matches known injection patterns. Nothing is withheld. Safe to register on a
  # host that does not dispatch it (Petasos logs which of the four availability
  # outcomes it saw and carries on).
  - transform_tool_result
  # Hermes approval observers. Return values are ignored. Recorded even while
  # Petasos enforcement is disarmed.
  - pre_approval_request
  - post_approval_response
```
<!-- PET-170-MANIFEST-END -->

The shipped manifest is `hermes-plugin/petasos/plugin.yaml`. Install it with
`petasos hermes install` and check it with `petasos doctor`. The Petasos tab
in Hermes's dashboard is the operator surface.

`pre_approval_request` and `post_approval_response` record Hermes approval prompts
on the enforcement spool (`event_type` approval). The request row has no choice.
The response row carries the operator choice. Disarm does not skip these records.
Petasos does not answer the prompt.

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

Install the Hermes plugin with `petasos hermes install` and check it with
`petasos doctor`. The operator surface is the Petasos tab in Hermes's dashboard.
Key behaviors to preserve in any custom integration:

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
  Membership governs the **argument** axis only. Result scanning inverts:
  unknown non-empty names are scanned; `NON_INGESTING_TOOLS` is the
  exclusion set the `transform_tool_result` seam gates on.
  `INGESTION_TOOLS` remains the named hook-reaching ingesting subset and
  is no longer the seam's membership test. Everything not in
  `READ_ONLY_TOOLS` is treated as dangerous for `param_scan_unsafe`
  enforcement. ML on this widened population is the 2,048-character
  `inspect()` head plus a base-install syntactic floor.
- **Graceful degradation.** Missing `PETASOS_SESSION_SECRET` disables HMAC
  binding; a missing config section falls back to defaults (all features
  enabled). The plugin never crashes Hermes.
- **Profile-aware config resolution.** The plugin uses
  `resolve_hermes_config_path()` to find `config.yaml`. When Hermes has set a
  home override, that home wins and the resolution tier is `override`. With no
  usable override the order is `HERMES_HOME`, then the active profile, then
  the v0.15 root. The override is host-controlled: Hermes sets it before
  `register()`, and the capture does not read tool arguments, session text, or
  the console request body. The plugin enforcement binding is the resolution
  captured at `register()`. Console equipped surfaces pass `use_override=False`
  and read the process binding. Those two files are the same only when the
  process binding and the captured home are the same path. Hermes normalizes
  the case of the home path in its own log line (`os.path.normcase`, so
  lowercase on Windows and unchanged elsewhere), and the launch home logs
  `tier=override`. A hook whose
  override home disagrees with the captured home logs
  `PETASOS_ARMED_RESOLUTION_WARNING captured=<path> hook=<path> reason=home_mismatch`:
  the homes disagree, and enforcement stays on the capture. The comparison
  resolves symlinks, junctions and Windows short names on both sides and folds
  case where the platform does, so two spellings of one directory never warn.
  Only the hook side expands `~`, so a literal `~` capture warns against its
  expanded hook home.

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

  # Session features (all default true)
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
| `fail_mode` | `"degraded"` | `"closed"` | Degraded blocks on partial or total ML failure. Production still prefers closed because closed also stops immediately on a critical pattern-scan finding. |
| `host_id` | `""` | Set to a stable ID | HMAC session binding needs a non-empty `host_id`; changing it invalidates all session tokens |
| `anonymize` | `false` | `true` | PII detection plus hash anonymization for audit correlation |

## How Petasos composes with Hermes approvals

Petasos does not replace Hermes approval. On a dangerous tool the plugin may
return action "approve" with a rule_key and a message. Hermes at or after
commit 64a6f42cb3 (2026-08-24) routes that return into its own operator
prompt when hermes_cli.plugins.get_pre_tool_call_directive is present, and
fails closed when nobody answers. Silence is not consent. An operator
"always" is stored under plugin_rule:<rule_key> in command_allowlist. The
keys Petasos sends are the finding rule id, or petasos.degraded. Petasos
honors always for that key: the key is not blocked and not prompted, including
under YOLO and under the block posture. Always on petasos.degraded skips the
degraded block and the degraded prompt, then the call still faces any other
key. Always on one command key leaves a different command key on the same
call to be approved or blocked on its own. Injection, source-taint, and PII
egress still block. command_allowlist is one store per Hermes profile home.
An always entry in the active profile home applies across Petasos profiles
on that home, including from code_generation to customer_service. It does
not waive a key while a routed secondary profile is active. It still applies
to that rule_key only.

code_generation sets dangerous_tool_posture to approve. The other built-in
profiles set block, which is also the default. Under block, a degraded scan
and a HIGH command finding quarantine the dangerous tool, except a key the
operator has marked always. Under approve, those two cases ask Hermes, and
only after source-taint egress, a non-command HIGH finding, and HIGH PII sent
to an egress sink have been checked. Those still block. The degraded approve
is returned on every degraded-only dangerous call until a confirmed session
or always response for plugin_rule:petasos.degraded records the session. A
once answer, a deny, a timeout, a cancelled answer, a notify failure, an
empty choice, and no answer leave the session unrecorded, and the next
degraded-only call asks again. A later YOLO or block posture still blocks a
recorded session unless the key is always-approved. After a confirmed session
or always, a command finding on a later call asks or blocks on the command
key. Until then, a degraded call that also has a command finding is prompted
as petasos.degraded.

Petasos records that Hermes prompt on the enforcement spool as an approval
event (a request row, then the choice on the response). The spool approval
row remains the persisted record, and the gate does not read it back. Hosts
that never fire the post hook do not fall back to recording the session when
the approve is returned. A call that reaches pre_tool_call without a Hermes
session_id or turn_id (for example, tools dispatched from code execution or
the tools MCP bridge) is prompted on every degraded-only dangerous call,
because the plugin cannot match a response to a session without them. The
once-per-session record is in-process: a restart re-arms the prompt.
disabled_scanners is read at
startup, so disabling an unusable backend there takes effect at the next
restart and removes the degraded condition itself.

YOLO (HERMES_YOLO_MODE set, or the session yolo flag) auto-approves a plugin
approve return. Petasos therefore returns block instead of approve for both
the degraded case and a HIGH command finding while YOLO is on, except a key
already marked always. Operators who run YOLO and want no Petasos quarantine
should set petasos.enabled to false. Hermes keeps its own hard-line command
patterns under YOLO.

On a host that does not expose the approve directive (absent at c6b0eb4de0,
2026-06-15), an approve return would be ignored and the tool would run.
Petasos probes once at startup and returns block wherever it would have
returned approve.

fail_mode degraded marks content unsafe on partial or total ML failure. It is
not a permissive mode. Zero ML scanners leave the syntactic verdict. A backend
that is installed but unusable stays registered so it fails loudly. Add its
id to disabled_scanners to opt out a probe-failed backend. A pipeline hook
error with no findings (frequency, escalation, anonymize, audit, or alert)
still sets param_scan_degraded. The operator log carries that pipeline error.
The key is still petasos.degraded. The cold-start window still blocks
dangerous tools under every fail mode except open, and does not use posture.
A guard evaluation that fails before a guard result exists is PET-224: the
reasons "guard evaluation unavailable: evaluation_timeout" and "guard
evaluation unavailable: evaluation_error" always block a dangerous tool.
They are not an approve, and always and the once-per-session record do not
apply to them.

The Observability tab lists refused approvals for the profile you have open:
`deny`, `timeout`, `cancelled`, `notify_failed`, and `smart_deny`. A guardian
deny that a person then answered is replaced by that answer. The list needs a
plugin copy at PET-222 or later to receive any approval rows, and PET-223 or
later for the command excerpt. "no approval events recorded" usually means an
older copy. The approve prompt's last clause, after `Command (from tool
arguments): `, is a redacted, quoted excerpt of the tool arguments. One
`name="value"` part is shown per argument. `\n`, `\"`, `\\`, and `\uXXXX` stand
for a real line break, quote, backslash, or control character in the argument.
`(invisible characters removed)` means the argument contains invisible
characters the prompt does not show. A cut excerpt (`(+N chars not shown)`, or
a prompt cut by the chat platform) is never enough to approve on. PET-251
redacts original string values before display normalization and JSON encoding,
including nested arguments, while leaving execution arguments unchanged.
An excerpt is withheld if redaction fails or its input exceeds the character,
16-level nesting or 4,096-node traversal limit. Total text sent through leaf
redaction is also bounded by the character budget, including repeated field-name
context for list values; unsupported argument objects
are also withheld. This does not change the approval decision. Approvals
Hermes parks with no notifier, YOLO, approvals off, and already-approved
patterns never fire the hooks and never appear. `transport_*` outcomes are
counted as unknown. Setting, changing, or first adding `session_secret` makes
earlier history rows and reviewed marks unverifiable, so previously overridden
refusals reappear as flagged items and marks must be redone. A forged row is
ignored for grouping on the equipped view. An undrained spool row of another
profile cannot be verified from this console. On a non-gated loopback dashboard
the session token is readable from `GET /`, so the embedded mark is reachable
by any local process. OAuth-gated mode or `withhold_session_token` closes that.

### What stays at defaults

For password-manager setup, credential-handling notices and the operator
rotation procedure, see [Credentials and reports](credentials.md).

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
  read-only set is *code* (`_TOOL_AXES_ROWS` in `petasos/guard/guard.py`,
  not `_TOOL_AXES`, the immutable `MappingProxyType` built from it),
  canonicalized at load into `_READ_ONLY_CANON`, which `_is_dangerous()`
  consults directly. Customize either axis by adding a row to
  `_TOOL_AXES_ROWS` with a conforming `evidence` anchor, then update the
  membership and count pins in `tests/test_tool_axes.py`. Adding an
  `acts=False` row grants an argument-side exemption and does not by itself
  add ingestion scanning; `search_files` is `acts=False` so a
  `config_ref` selfmod finding on a search of an owned path is an accepted
  FP, compensated by the ingestion scan. Edit the table in
  `petasos/guard/guard.py`, not `config.yaml`.

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
INFO  petasos.plugin: Presidio backend verified, scanner active
INFO  petasos.plugin: PromptGuard backend verified, scanner active
INFO  petasos.plugin: Petasos initialized: scanners=['minimal', 'presidio', 'prompt_guard'], unavailable=[], fail_mode=closed, host_id=...
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

### Verification

The reference plugin's `verify.py` is retired. Install with `petasos hermes install`, check with `petasos doctor`, and use the Petasos tab in Hermes's dashboard.

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
2. Install the plugin into that home with `petasos hermes install` and check it
   with `petasos doctor`.

   The plugin files and the `petasos` library in Hermes's venv must move
   together. The plugin imports `format_result_notice` at module level and
   `build_scanners` inside its deferred init, and `build_scanners` shipped
   first, so any library too old for this plugin also misses
   `format_result_notice`: the plugin does not import at all and nothing is
   enforced. Check the host's plugin-load error, and treat the absence of the
   `Petasos plugin registered` INFO line in the startup log above as the
   reliable signal. An old-library skew therefore does not latch init. A
   library *newer* than a stale plugin copy still can, if a symbol or
   signature the deferred init uses has moved. Run `petasos doctor` before
   restarting. Between a sync and its restart the per-profile rows FAIL on the
   gateway's load line, because the running process still holds the old bytes;
   that is expected, and the row says to restart. Sync the library before the
   plugin files: a `dashboard/plugin_api.py` ahead of the library fails `/armed`
   until the library catches up. The scanner-imports check still probes `build_scanners` only, so
   that row FAILs a library too old for `build_scanners` and PASSes one that has
   `build_scanners` but still lacks `format_result_notice`. Since PET-189 the
   config validation and feature activation rows import this plugin file, so that
   module-level skew FAILs there with the import error instead of passing unseen.
   The arming state row stays independent of that import, so the armed bit is
   still readable when the plugin copy is skewed. Init otherwise latches on a
   config or pipeline
   construction error, and the session then runs on the syntactic fallback:
   dangerous tool calls are blocked under the default `degraded` fail-mode,
   read-only tools are still allowed, until the process is restarted. The
   latched error text appears in the console's `init_failed` row.

3. Restart Hermes Desktop.

If the plugin files are absent from the resolved home, enforcement is **silently
off**: no error, no log warning (the plugin simply isn't discovered). The
`petasos doctor` and the `loading config from ...` INFO line are the primary
diagnostic tools.

### One copy per guarded profile

A multiplexed gateway serves several profiles, and each profile home discovers
plugins only in its own `plugins/`. The dashboard does fall back to the root, so a
console can look fine with no hook behind it. Guard a profile by giving that home
its own copy. A profile with no copy stays unguarded, and that is a supported
choice: nothing installs itself, and `petasos doctor` reports it as not
protected, with the next steps and a line saying no action is needed if it is
intended.

**Backups never go in `plugins/`.** Hermes selects by the manifest `name`, not the
folder name, and the last folder in sorted order wins. So `petasos.bak-20260728`
beats `petasos` with no warning, and a sync into `plugins/petasos` changes nothing.
One folder deeper still loads as a second plugin. Keep backups in
`<home>/petasos-plugin-backups`, beside `plugins/`. Cloning a home copies whatever
is in `plugins/`, so do not clone a home that holds a backup.

The reference plugin's `verify.py` and the standalone console are retired.
Install with `petasos hermes install`, check with `petasos doctor`, and use the
Petasos tab in Hermes's dashboard.

## PromptGuard model prerequisites

The `prompt_guard` backend uses the gated Hugging Face model
`meta-llama/Llama-Prompt-Guard-2-86M`. To use it:

1. **Accept the access terms.** Visit
   [the model page](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M)
   and accept Meta's access terms from the Hugging Face account you will use.
2. **Pre-download the pinned revision** (recommended), with `HF_TOKEN` set for this
   command or after `hf auth login`. The download needs that account's token. A
   cached model then loads with no network call, so the token can be removed:
   ```bash
   hf download meta-llama/Llama-Prompt-Guard-2-86M --revision a8ded8e697ce7c355e395a0df51f94adb4a2fd27
   ```
   The model is cached under `HF_HOME` (default `~/.cache/huggingface`), about 1.1 GB.
3. **Or make a token available** to the gateway process, through `HF_TOKEN`,
   `HUGGING_FACE_HUB_TOKEN`, `HF_TOKEN_PATH`, or `<HF_HOME>/token`.

**Where the token goes on a multiplexed gateway.** Hermes does not load a routed
profile's `.env` into the process environment, and the scanner runs in that shared
process, so a token in `profiles/<name>/.env` is not seen. Use a pre-download, the
launch home's `.env`, the scheduled task's environment, or the token file.

If the prerequisites are missing, every scan through the backend returns an error
naming the revision and the download command. Petasos never prompts for credentials.
A later scan recovers with no restart once the model is cached.

**Cold start blocks.** The model loads on the first scan that needs it, not at
startup, so under `closed` or `degraded` a restart blocks tool calls in every guarded
copy until it is in memory. Measured with three copies on Windows, Python 3.14, CPU
with 8 torch threads and a warm disk cache: 7 to 9 seconds to the first clean result
per copy, with one model shared. Expect longer from a cold disk. A truly hung load
keeps returning the warming-up error, and its thread can delay interpreter exit.

**Memory.** Peak working set in that same measurement: about 3.8 GiB for three copies
after a concurrent load (3.6 GiB after load alone). PromptGuard alone is about 1.8
GiB, and it is shared. Presidio alone is about 1.0 GiB, and each guarded copy builds
its own analyzer. The dashboard's own pipeline counts as one more copy where it runs
in the gateway.

**torch changes Presidio.** spaCy's `thinc.compat` imports torch when it can, so
listing `prompt_guard` in `disabled_scanners` neither removes a broken torch's effect
on Presidio nor reclaims its memory.

### Upgrading to the PromptGuard backend

The backend registers even when absent, so a host can block all content under
`closed` or `degraded`:

- A host with `presidio` disabled still turns `safe=False` until it adds
  `prompt_guard` to `disabled_scanners` or installs the extra with the model
  prerequisites met.
- A fresh `petasos[all]` host blocks until the model prerequisites are met or
  `prompt_guard` is listed in `disabled_scanners`.

**Operator note for this deployment.** Root, gibson and ops stay disarmed until the
live sync under PET-234. Each guarded profile then runs minimal, presidio and
prompt_guard.

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
  `petasos doctor` to confirm the resolved path.

### Scanner import failures

```text
INFO petasos.plugin: PromptGuard not installed: ML injection detection unavailable
```

A backend that is missing is not graceful under `closed` or `degraded`: a registered
backend that cannot load blocks all content. Install it, through the plugin manifest
on a Hermes generation, or list it in `disabled_scanners`. The syntactic pre-filter
(23 regex rules) still runs without ML, and under `open` it is all that runs.

**Venv-rebuild dep loss (silent).** A Hermes venv rebuild can drop transitive
dependencies the ML backends import indirectly. The classic failure is a missing
`packaging`, which makes spaCy/thinc raise on import and takes Presidio down with
it even though the plugin manifest declares it. After any rebuild, check that the
plugin's `pyproject.toml` still declares the backends, and confirm which backends
actually loaded from the plugin health endpoint (`/api/plugins/petasos/health`)
rather than assuming the install succeeded.

### Config section wiped

The `petasos:` section is a top-level key, so it survives UI model switches. If it
disappears, check for concurrent `config.yaml` editors or a Hermes update that
overwrote the file.

### Config split-brain

The reference plugin's split-brain check is retired. Check the install with
`petasos doctor`. The profile config is the one the running processes use:
update the root config to match, or remove the root's `petasos:` section to
eliminate the drift.

### ToolCallGuard constructor error

```text
ERROR petasos.plugin: ToolCallGuard.__init__() missing 2 required positional arguments
```

`ToolCallGuard` requires `(pipeline, frequency_tracker, config)`. The Hermes
plugin wires this automatically (`petasos hermes install`). In a custom integration, construct a
`FrequencyTracker(config)` and pass it.

### Model claims a blocked command ran

The model may claim a blocked command "ran but produced no output." This is a
model-behavior issue, not a Petasos one. Make the block message explicit (include
`[BLOCKED]` and `was NOT executed`) so the model reports accurately.
