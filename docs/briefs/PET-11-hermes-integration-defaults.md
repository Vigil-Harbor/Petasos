# PET-11 Brief — Hermes Desktop Integration: Stock → Production Delta

> **Status:** DRAFT
> **Date:** 2026-05-30
> **Source:** GPT-5.5 pre-ship gate review (PET-11 comment, 2026-05-30) + `hermes-desktop-footguns.md`
> **Audience:** Implementer wiring Petasos into a Hermes Desktop install (macOS or Windows)

---

## Problem Statement

Petasos ships with developer-friendly defaults: `fail_mode="degraded"`, all premium features disabled, no ML scanner requirement, no session secret. These are correct for library distribution — `pip install petasos` should work without ceremony.

But Petasos exposes *affordances* that only become *enforcement* if the host wires them correctly. A stock Hermes Desktop install with `pip install petasos` and no config changes has no security enforcement active. This brief documents every change from out-of-the-box to a properly secured deployment.

---

## Decisions Carried Forward

1. **Petasos defaults are library defaults, not deployment defaults.** The `PetasosConfig()` constructor produces a safe-to-import, zero-enforcement config. Deployment hardening is the host's responsibility.
2. **Integration surface is shell hooks, not code fork.** Per footguns doc §10 recommendation: shell hooks (`pre_tool_call`) for separation, top-level `petasos:` config key for persistence.
3. **Both platforms.** Every change below must work on macOS (`~/.hermes/`) and Windows (`%LOCALAPPDATA%\hermes\`). Hook scripts run under Git Bash on Windows (100-200ms overhead per invocation — §4a footgun).

---

## Stock → Production: Required Changes

### 1. Install ML scanner backends

**Stock:** `pip install petasos` — zero ML deps, syntactic pre-filter only (17 regex rules).
**Production:** `pip install petasos[all]` — adds LLM Guard (DeBERTa-v3), LlamaFirewall (PromptGuard 2, AlignmentCheck, CodeShield), Presidio (PII detection + anonymization).

**Why this matters:** `fail_mode="closed"` cannot protect against ML scanner outage if no ML scanners were configured in the first place. The syntactic pre-filter catches known patterns but cannot do semantic detection.

**Startup verification:** Hermes init should verify expected scanner backends are importable and responding before accepting traffic. Petasos does not enforce this — the host must.

**Platform note (Windows):** Scanner packages must be installed in the same Python environment Hermes uses. MINGW64 Python ≠ system Python ≠ WSL Python (footguns §5). Verify `python -c "from petasos.scanners import LlmGuardScanner"` succeeds in Hermes's Python.

### 2. Set `fail_mode="closed"`

**Stock default:** `fail_mode="degraded"` — partial or total ML failure marks content unsafe; open mode would pass through.
**Production override:** `fail_mode="closed"` — same blocking behavior plus early-exit on CRITICAL syntactic findings.

```yaml
# ~/.hermes/config.yaml (macOS) or %LOCALAPPDATA%\hermes\config.yaml (Windows)
petasos:
  fail_mode: "closed"
```

**Why:** `degraded` is too permissive for a security product in production. The GPT-5.5 review flagged this as the #3 deployment enforcement gap.

**Config survival:** `petasos:` is a top-level key — survives UI model switches (footguns §2 — `setModelAssignment()` only wipes keys under `model:`).

### 3. Configure `session_secret` and `host_id`

**Stock default:** `session_secret=None`, `host_id=""` — session tokens are unauthenticated bare strings.
**Production requirement:** Both must be configured. Without them, the FREQ-03 session-spoofing defense (HMAC-SHA256 binding) is inactive.

```yaml
petasos:
  session_secret: "<base64-encoded 32+ byte secret>"
  # host_id is set in Pipeline() constructor, not config.yaml
```

`host_id` is a Pipeline constructor parameter (not a config field) — Hermes must pass a non-empty, stable machine identifier. `Pipeline(config, host_id="hermes-gavin-01")`. If `session_secret` is set but `host_id` is empty, Pipeline raises `ValueError` at construction time.

**Generation:** `python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"` — run once per deployment, store in `.env` file (not config.yaml), reference via `${PETASOS_SESSION_SECRET}`.

### 4. Activate premium license at startup

**Stock default:** All premium toggles `False`. `Pipeline` auto-activates from `PETASOS_LICENSE_KEY` env var if present.
**Production requirement:** Valid JWT in `PETASOS_LICENSE_KEY` or explicit `pipeline.activate(key)` call. Hermes must verify that frequency, escalation, tool_guard, audit, and alerting all report `available` before accepting traffic.

```python
state = pipeline.activate(license_key)
assert state == LicenseState.VALID

# Verify all premium features unlocked
for feature in ("frequency", "escalation", "tool_guard", "audit", "alerting"):
    assert pipeline.is_premium_active(feature), f"{feature} not available"
```

**Config toggles still apply:** Premium activation unlocks the *capability*; the per-feature booleans (`frequency_enabled`, `escalation_enabled`, etc.) must also be `True` in config.

```yaml
petasos:
  frequency_enabled: true
  escalation_enabled: true
  tool_guard_enabled: true
  audit_enabled: true
  alert_enabled: true
```

### 5. Route every tool call through ToolCallGuard

**Stock behavior:** ToolCallGuard exists but is advisory — `evaluate()` returns `GuardResult` with `allowed`, `tier`, `param_scan_unsafe`, and `findings`. It does not block anything by itself.
**Production requirement:** Hermes must call `ToolCallGuard.evaluate()` before every tool execution and enforce the result.

**Integration contract:**

| GuardResult field | Hermes action |
|---|---|
| `allowed=False` | Block the tool call, return block reason to model |
| `allowed=True, param_scan_unsafe=True` | Block/quarantine for dangerous tools (exec, write_file, patch, terminal). Log-and-continue for read-only tools |
| `findings` with HIGH/CRITICAL severity | Block/quarantine for dangerous tools regardless of `allowed` |
| `tier="tier3"` | Terminate session immediately |

**Critical gap (GPT-5.5):** The most likely integration-level miss is `allowed=True` with `param_scan_unsafe=True`. Guard returns allowed because the tool is in the exempt list, but the parameter scan found an injection payload. Hermes must not treat `allowed=True` as unconditional pass.

**Test case needed:** `test_guard_allowed_true_with_param_scan_unsafe_blocks_dangerous_tool` — this exercises the exact scenario.

**Dispatch paths (footguns §1):** File tools (`read_file`, `write_file`, `patch`, `search`) run inside the Electron process, not through the terminal backend. Docker sandboxing does not cover them. The guard must intercept *both* dispatch paths — terminal tool calls AND in-process file tool calls.

### 6. Wire audit + alerting callbacks

**Stock default:** `on_audit=None`, `on_alert=None` — events are generated but discarded.
**Production requirement:** Hermes must provide callback functions to Pipeline constructor:

```python
pipeline = Pipeline(
    config=config,
    scanners=[minimal, llm_guard, presidio],
    host_id="hermes-gavin-01",
    on_audit=lambda event: log_audit_event(event),
    on_alert=lambda alert: handle_security_alert(alert),
)
```

Callbacks are exception-isolated (BaseException caught, recorded on `PipelineResult.errors`) — they cannot crash the pipeline. But silent failure means no observability if the callback itself is broken.

---

## Config Template: Production Hermes Desktop

```yaml
# ~/.hermes/config.yaml — top-level petasos section
petasos:
  enabled: true
  fail_mode: "closed"
  
  # Normalization (all true by default — leave as-is)
  normalize_nfkc: true
  strip_zero_width: true
  map_homoglyphs: true
  detect_rtl_override: true
  
  # Scanners configured in Python init, not YAML
  # But scanner extras must be pip-installed
  
  # PII anonymization
  anonymize: true
  pii_entities: ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD"]
  redaction_mode: "hash"
  # hash_key via env var: ${PETASOS_HASH_KEY}
  
  # Premium features (all require valid license)
  frequency_enabled: true
  escalation_enabled: true
  tool_guard_enabled: true
  audit_enabled: true
  alert_enabled: true
  audit_verbosity: "standard"
  
  # Session binding
  # session_secret via env var: ${PETASOS_SESSION_SECRET}
```

```bash
# ~/.hermes/.env (macOS) or %LOCALAPPDATA%\hermes\.env (Windows)
PETASOS_LICENSE_KEY=eyJhbGciOiJFZERTQSIs...
PETASOS_SESSION_SECRET=<base64-encoded-32-byte-secret>
PETASOS_HASH_KEY=<random-string-for-hmac-anonymization>
```

**Env var credential isolation (footguns §6):** `PETASOS_LICENSE_KEY`, `PETASOS_SESSION_SECRET`, and `PETASOS_HASH_KEY` match the `*_KEY`, `*_SECRET` patterns and are automatically stripped from terminal subprocess environments by Hermes's `_build_provider_env_blocklist()`. They will NOT leak into agent-executed commands.

---

## What Does NOT Change from Stock

These Petasos defaults are correct for production — no override needed:

| Setting | Default | Why it's fine |
|---|---|---|
| `scanner_timeout_seconds` | 10.0 | Generous for cold-start, bounded at ≤60 |
| `scanner_circuit_breaker_threshold` | 3 | 3 consecutive timeouts before short-circuit |
| `tier1_threshold` | 15.0 | Inherited from Drawbridge, battle-tested |
| `tier2_threshold` | 30.0 | Same |
| `tier3_threshold` | 50.0 | Floor is hardcoded at 30.0 — cannot go lower |
| `session_ttl_seconds` | 3600.0 | 1-hour TTL matches typical chat session |
| `max_sessions` | 10,000 | Generous for single-host desktop |
| Normalization toggles | all `True` | No reason to disable any |

---

## Platform-Specific Notes

### macOS

Straightforward path. Hermes uses system shell, Python 3.11+ from installer or Homebrew, no translation layers. Hook scripts run natively. Config at `~/.hermes/config.yaml`.

### Windows

Per footguns doc, watch for:

1. **Git Bash overhead (§4a):** Hook scripts spawn via MINGW64 — add 100-200ms per tool call. For Python-heavy scanners, consider a long-lived daemon that the hook script curls into.
2. **Python path confusion (§5):** Ensure scanner packages are installed in Hermes's bundled Python, not system/WSL Python.
3. **Process signals (§9):** SIGTERM is unreliable. Scanner subprocess cleanup needs Windows-aware patterns (`taskkill` / `CREATE_NEW_PROCESS_GROUP`).
4. **Config atomicity (§11):** If Petasos writes config.yaml programmatically, use atomic write-and-rename. Direct `open(path, 'w')` risks corruption with concurrent Desktop UI saves.
5. **First-use consent (§4b):** Each hook command triggers a one-time TTY consent prompt. Desktop sessions are interactive so this fires on first boot after config change.

---

## Responsibility Chunking

This is a coordinated three-role effort:

### Planner (Cowork session — this brief)

- Defines the integration contract (this document)
- Maps Petasos defaults → production overrides
- Identifies platform-specific footguns
- Creates the test case spec for `test_guard_allowed_true_with_param_scan_unsafe_blocks_dangerous_tool`
- Posts info relay to PET-12 for docs/README consumption

### Iterator (Local Claude Code + Devin)

- Writes the integration test (`test_guard_allowed_true_with_param_scan_unsafe_blocks_dangerous_tool`)
- Writes the Hermes integration fixture from PET-11 scope item 1
- Validates config template against `PetasosConfig.from_dict()` round-trip
- Runs the full test suite after integration test lands

### Operator (Remote Claude Code + Devin)

- Implements the Hermes-side wiring (hook script, config injection, startup verification)
- Validates on both macOS and Windows
- Wires `on_audit` / `on_alert` callbacks into Hermes's logging/observability
- Tests the `petasos:` config key survival across UI model switches

---

## Done When

- [ ] Integration brief reviewed and accepted (this document)
- [ ] `test_guard_allowed_true_with_param_scan_unsafe_blocks_dangerous_tool` exists and passes
- [ ] Config template validated via `PetasosConfig.from_dict()` round-trip test
- [ ] PET-12 comment posted with integration contract summary for docs consumption
- [ ] Hermes-side hook script prototype exists for at least one platform

## Out of Scope

- Hermes source code modifications (Petasos integrates via hooks and in-process import, not code changes)
- Docker backend scanner baking (footguns §12 — unnecessary coupling)
- Custom MCP server for Petasos (future consideration, not v1.0.0)
- Frontend security alert UI (footguns §14 — hook stdout flows inline into conversation; dedicated UI is post-v1)
