# Deployment hardening checklist

Where Petasos sits in your security model, and what to pair it with. Short
version: **Petasos is a detection layer, not a boundary.** Every claim below
carries a code reference so this document can be audited against the source
it describes.

## 1. What Petasos is — and is not

Petasos is a heuristic detection layer over attacker-influenced strings. It
scans, scores, and flags; it does not contain. The same stance as upstream
Hermes ([SECURITY.md](https://github.com/NousResearch/hermes-agent/blob/main/SECURITY.md)):
*the only security boundary against an adversarial LLM is the operating
system.* Detection layers are useful. They are not boundaries.

Two incidents from June 2026 make the residual risk concrete:

- **ML backends can be silently absent.** A scanner extra that fails to
  import leaves you with less coverage than you configured (PET-87 — scanner
  init now logs honestly and health reflects reality).
- **ML backends can be broken in-process.** A backend that imports but
  misbehaves degrades coverage without crashing anything (PET-92).

In both cases the **syntactic pre-filter is the only always-on layer** — it
has zero ML dependencies and runs unconditionally in every scan
(`petasos/scanners/minimal.py`). This is why `fail_mode` defaults to
`degraded` — partial or total ML scanner failure marks content unsafe rather
than waving it through (`petasos/config.py:56`).

**Checklist:**

- [ ] Treat Petasos verdicts as signals for policy, not as containment.
- [ ] Run it inside an OS-level sandbox story, not instead of one (§5).
- [ ] Verify at startup that the scanners you configured actually loaded
      (the console health panel and scanner init logs tell the truth —
      PET-87).

## 2. Console binding

The standalone console binds to loopback by design: `serve()` hardcodes
`host="127.0.0.1"` with default port `8384`
(`petasos/console/__init__.py:34-39`).

- [ ] Keep it on loopback, or reach it through Tailscale/WireGuard.
- [ ] Never rebind to `0.0.0.0` or put it behind a plain reverse proxy —
      the standalone console has **no authentication of its own**.
- [ ] In Hermes plugin mode the console rides Hermes' own session-token
      auth (PET-83); the same network posture still applies.

That "no authentication of its own" default is also a self-disarm path: a
loopback `POST /api/armed` flips the master Equipped bit with zero credentials.
See section 6 for the full self-disarm / self-tamper threat and the optional
`PETASOS_CONSOLE_TOKEN` that gates the `/api/*` routes.

## 3. Secrets

Two secrets, both environment-variable-first, never committed config:

| Secret | Purpose | Handling |
|---|---|---|
| `PETASOS_SESSION_SECRET` | HMAC session binding (FREQ-03) **and** enforcement-spool integrity (PET-139); see [§3.1](#31-enforcement-spool-integrity-pet-139) | base64 in env; decoded at dashboard init (`petasos/console/hermes/plugin_api.py:65-73`). Invalid base64 → a warning is logged and **session binding is silently disabled** — watch for that log line. |
| `PETASOS_HASH_KEY` / `hash_key` | HMAC key for hash-mode PII anonymization | env override at `plugin_api.py:75-77`; required non-empty when `anonymize=True` and `redaction_mode="hash"` (`petasos/config.py:139-142`, SCAN-05). |

Leak resistance is built in — and worth knowing the exact shape of:

- `session_secret` is **never serialized**: `PetasosConfig.to_dict()` skips
  the field unconditionally (`petasos/config.py:381-382`), so it cannot
  appear in config exports, API responses, or audit snapshots at all.
- `hash_key` is a registered secret field (`petasos/config.py:40`) and
  serializes as `[REDACTED]` whenever `redact_secrets=True`
  (`petasos/config.py:384-385`) — which is how verbose audit snapshots
  (`petasos/session/audit.py:121`, AUD-03) and console config reads
  (`petasos/console/server.py:132`) call it.

**Checklist:**

- [ ] Source both from env or a secret manager; never write them into
      `config.yaml`.
- [ ] Generate them with real entropy (see
      [hermes-desktop.md §2](hermes-desktop.md#2-generate-credentials) for one-liners).
- [ ] If you set `PETASOS_SESSION_SECRET`, also configure `host_id` —
      the pipeline requires it when a session secret is present
      (`petasos/pipeline.py:225-226`).
- [ ] Grep your logs once after deploy for the invalid-base64 warning;
      binding that silently disabled is worse than binding you never
      configured.

### 3.1 Enforcement-spool integrity (PET-139)

`PETASOS_SESSION_SECRET` does double duty. Beyond FREQ-03 session binding it is
the root of a keyed-HMAC attestation on the cross-process enforcement spool
(`petasos-enforcement.jsonl`). The gateway (writer) stamps every enforcement
event with an HMAC over a canonical serialization of the record; the dashboard
(reader) recomputes and verifies before trusting the row. A row that fails
verification is still surfaced, but flagged `unverifiable` in the drill-down
panel and never counted as a trusted block. The on-the-wire key is a
domain-separated subkey, `HMAC-SHA256(session_secret,
"petasos/enforcement-spool/v1")`, not the raw secret, so the two uses cannot
cross-interfere.

**The env contract (the one thing to get right):** integrity only holds when
the writer and the reader derive the same key, and they are separate processes.
That reduces to one rule: every process that touches the spool must launch with
the identical `PETASOS_SESSION_SECRET`. In a gateway-paired deployment that is
the gateway process and the dashboard process sharing one secret in their
environment. For the low-level `serve()` / `create_app()` API the caller owns
`session_secret` on the pipeline config it passes; populate it the same way
(decode `PETASOS_SESSION_SECRET` into the config) to get attestation on that
path. A writer-key / reader-key mismatch is a misconfiguration, not a silent
blind spot: it surfaces as a burst of `unverifiable` rows plus the log token
below with class `sig-mismatch`.

**No secret set?** Integrity is simply off. Every event is `unattested`,
surfaced and counted exactly as before PET-139. Setting the secret is opt-in;
not setting it is the documented no-regression posture, not a downgrade.

**Upgrade step (do this once, when first enabling integrity).** On a host that
has already been running, the spool on disk still holds pre-PET-139 unsigned
events. Those are genuine but unattestable, so they would surface as a one-time
burst of `unverifiable` rows. To avoid that artifact, clear the live spool file
**and** remove any `<spool>.rot` segment beside it before (re)starting with the
secret set:

```bash
rm -f "<config-dir>/petasos-enforcement.jsonl" "<config-dir>/petasos-enforcement.jsonl.rot"
```

(`<config-dir>` is the resolved Hermes config directory, e.g.
`%LOCALAPPDATA%/hermes/...` on Windows.) The block tally is in-memory and resets
on a dashboard restart anyway, so clearing the spool loses only already-drained
telemetry. Removing the `.rot` too matters: an orphan `.rot` recovered later
would replay the same legacy-unsigned burst.

**The greppable tripwire.** Every verification failure emits a rate-limited
WARNING carrying the token `PETASOS_INTEGRITY_UNVERIFIABLE`, a failure class
(`sig-missing` for an absent tag, `sig-mismatch` for a wrong one), the
`scan_id`, and the `session_id`. `sig-mismatch` points at a forging process or a
key mismatch; `sig-missing` over a freshly-enabled host is usually the
legacy-unsigned rollout artifact above.

**Threat model (what this does and does not defend).** The delivered property is
forgery-evidence on the spool against a same-host process that is not Petasos
and does not hold `session_secret` trying to inject or forge enforcement rows.
It is **not** a defense against a compromised gateway (it legitimately holds the
key), an attacker who can read `PETASOS_SESSION_SECRET` from the environment or
config, byte-for-byte replay of a captured genuine line (it still verifies and
still inflates the block tally, a named v1 limitation), or network-level
tampering (that is PET-83's domain).

**Checklist:**

- [ ] For spool attestation, launch the gateway and the dashboard with the
      **same** `PETASOS_SESSION_SECRET`.
- [ ] On first enable over an existing host, clear the spool and its `.rot`.
- [ ] Grep deploy logs for `PETASOS_INTEGRITY_UNVERIFIABLE`; a steady stream of
      `sig-mismatch` means a key mismatch or a forging process, not noise.

## 4. Fail-mode

`fail_mode` controls what happens when ML scanners fail
(`petasos/config.py:53-56`):

| Mode | On ML scanner failure | Use when |
|---|---|---|
| `degraded` (default) | Content marked unsafe (`safe=False`) on partial **or** total ML failure; syntactic pre-filter still runs | You want fail-safe behavior and can tolerate false-positive blocks during outages |
| `closed` | Everything in `degraded`, plus early-exit block on CRITICAL findings from the syntactic pre-filter | Strictest posture; latency-sensitive blocking on the always-on layer |
| `open` | ML failures ignored — content passes with whatever the remaining scanners say | Only if availability beats detection. **Warning:** `open` + an ML outage = syntactic-only coverage, silently. |

- [ ] Keep `degraded` unless you have a written reason not to.
- [ ] If you choose `open`, pair it with alerting on scanner health so an
      outage is loud somewhere else.

## 5. Pair-with checklist (the actual boundary)

Petasos complements these; it replaces none of them. Pointers, not
duplication — the canonical source is
[Hermes SECURITY.md](https://github.com/NousResearch/hermes-agent/blob/main/SECURITY.md).

- [ ] **Terminal-backend isolation** — run the agent's shell in a container
      or VM, not on the host.
- [ ] **Gateway allowlists** — restrict which tools/commands the agent can
      invoke at the gateway layer.
- [ ] **Egress control** — limit where the agent process can connect;
      exfiltration is an egress problem, not a string-scanning problem.
- [ ] **Skills review** — treat third-party skills as code you ship.
- [ ] **Windows:** read
      [hermes-desktop-footguns.md](../platform/hermes-desktop-footguns.md)
      — on Hermes Desktop for Windows, **file tools bypass the terminal
      sandbox**, which directly bounds what Petasos can and cannot see.

## 6. Protect Petasos's own config (self-disarm / self-tamper)

The Equipped/Unequipped switch and the `petasos:` config block are a
human-operator escape hatch, not an agent-facing control. A guarded agent that
can reach `config.yaml`, the standalone console, or the embedded plugin API can
disable or relax its own enforcement. This is a deployment and boundary problem:
the fix is to put the config and console out of the agent's reach, not to teach
the guard to defend its own config file.

### The three vectors

- **A. Filesystem write.** The `enabled` bit and the rest of the config live in
  `config.yaml` (resolved by `resolve_hermes_config_path()`: `HERMES_HOME`, then
  the active-profile pointer, then the v0.15 root, all user-writable paths the
  agent operates in). `read_armed()` re-reads that file on the hot path (roughly
  a 1-second TTL), so a write of `enabled: false` disarms within about a second;
  `_pre_tool_call` then passes every call through with no enforcement. There is
  no path-based protection (classification is name-based by design, and PET-112
  deliberately exempts the agent's own local writes), so a write to `config.yaml`
  is indistinguishable from any other local write. The only residual is a
  rate-limited `PETASOS_DISARMED` WARNING: an audit breadcrumb, not a control.
- **B. Console HTTP API.** The standalone console binds loopback with no auth by
  default (see section 2). A loopback `POST /api/armed {"armed": false}` disarms
  with zero credentials, reachable by any http or shell tool. Loopback is not a
  control when the agent has a shell.
- **C. Config self-relaxation.** A hand-written but valid config can set
  `fail_mode: open`, `tool_guard_enabled: false`, an empty `egress_sink_tools`,
  and weakened tiers or alerts. `PetasosConfig` validation enforces internal
  consistency, not a minimum security posture.

### The mitigation (both platforms)

Place `config.yaml` and `$HERMES_HOME` outside the agent's writable filesystem
scope:

- **POSIX:** a read-only bind mount, or a separate uid that owns the config with
  the agent's uid denied write.
- **Windows:** a separate Windows user or service account owns the config
  directory, with an ACL that denies write to the agent's account. Note that
  `%LOCALAPPDATA%\hermes` is user-writable by default (and see the section 5
  Windows note: on Hermes Desktop for Windows, file tools bypass the terminal
  sandbox).

Then ensure neither the standalone console nor the embedded plugin API is
reachable by the agent's shell or http tools (network-namespace isolation, or no
shell/http tool in the agent's toolset). Loopback alone is insufficient.

> **All profile homes, not just the active one (PET-146).** Hermes 0.16+ keeps a
> separate `config.yaml` per persona under `profiles/<name>/`, and the Config
> Editor's Hermes-agent-profile selector enumerates and edits **every** one of
> them. A per-profile egress fence (`source_taint_namespaces`) or a relaxed
> `fail_mode` can be **pre-staged in a non-equipped profile** and arm on the next
> equip, so the read-only-mount / write-denying-ACL mitigation above must cover the
> **whole `profiles/` tree** (plus the v0.15 root and any `$HERMES_HOME`), not only
> the equipped profile's file. Background and the full two-axis model:
> [`profile-resolution-model.md`](./profile-resolution-model.md).

### Optional console token (`PETASOS_CONSOLE_TOKEN`)

The standalone console reads an optional bearer token from the
`PETASOS_CONSOLE_TOKEN` environment variable. When it is set to a non-blank
value, every `/api/*` route (including `POST /api/armed` and `PUT /api/config`,
plus the config and scan-history reads and the SSE stream) requires an
`Authorization: Bearer <token>` header; the HTML shell (`GET /`) and `/static`
assets still load so the page renders.

What it covers, and what it does not:

- It raises the bar against a network-only or non-shell HTTP caller (Vector B).
- It does **not** defend against an agent that can read the host environment or
  the config file. Under the common same-uid Hermes deployment the token lives in
  the agent's own process environment and is readable by a shell-capable agent
  (which could also just use Vector A). The primary mitigation remains deployment
  posture (config and console out of reach, separate uid or netns).

Operational notes:

- It is **off by default**, and a blank value (empty or whitespace) is also off
  (a single set-but-blank WARNING is logged). Verify it is on by observing a 401
  on an unauthenticated `/api` call, not by trusting a log line.
- The token is compared **verbatim**: do not rely on leading or trailing
  whitespace being meaningful, trimmed for you, or preserved in transit.
- The scheme match is case-sensitive (`Bearer`, not `bearer`).
- With the token on, the bundled browser UI cannot drive the `/api` routes by
  plain navigation (it sends no `Authorization` header yet): the shell loads but
  its panels show errors. Use an authenticated client or a reverse proxy that
  injects the credential, for example:
  `curl -H "Authorization: Bearer <token>" -X POST http://127.0.0.1:8384/api/armed -d '{"armed": true}'`.
- **Known limitation until the served-UI follow-up ships:** with the token on,
  the browser Observability tab still renders the equip banner as EQUIPPED even
  though its armed read is being 401'd. Do not trust the in-browser banner when
  the token is on; verify armed state with an authenticated `GET /api/armed`. The
  follow-up ticket carries in-UI token entry, graceful 401 handling, equip-banner
  correctness, and stopping the 10 second health/fallback polls on a 401.
- **Forward-looking invariant:** the dependency gates by the `/api/` path prefix,
  so every sensitive route must live under `/api/`. A future non-asset route
  added outside `/api/` would be served unauthenticated.

### The floor that survives a hostile config

Two invariants survive a relaxed-but-valid config: the Tier-3 floor
(`max(tier3, 30.0)`, an inline literal in `escalation.py`) and the unsuppressible
injection and structural rule set (`_UNSUPPRESSIBLE_RULE_IDS` in `minimal.py`,
subtracted from any caller-supplied suppress set). A hostile config cannot lower
the Tier-3 floor or suppress those rules, and both are pinned by regression
tests.

These floors are **moot once `enabled` is flipped**: Vectors A and B
short-circuit `_pre_tool_call` before any scan runs, so a disarmed pipeline never
reaches tier evaluation or rule matching. Do not mistake the floor for
self-disarm protection.

### Profile changes require a restart (the boot profile is pinned)

Petasos pins its config resolution **once, at plugin registration**, from the
operator-trusted boot environment (PET-130). Every armed-bit read and every live
config reload resolves through that boot pin, so a per-profile gateway process
enforces its own profile correctly for its whole lifetime. This is the supported
model on Hermes 0.16.x, where each gateway is a per-profile process with its own
`HERMES_HOME`.

The pin is captured at boot and is **not** re-derived on a profile change. If a
running gateway process is ever retargeted to a different profile **in place**
(a live profile swap with no process restart), Petasos keeps enforcing the
**boot** profile's policy: a disarm, a tier change, or any `petasos:` edit written
to the *new* profile is not picked up. For a security control that is the wrong
default, so the contract is explicit:

- [ ] **A security-relevant profile change requires a gateway/process restart.**
      Restart the gateway after switching the active profile; do not rely on a
      live swap to move enforcement. Confirm the new binding from the log line
      `PETASOS_ARMED_RESOLUTION tier=<t> path=<p>` (it names the `config.yaml` the
      running process is pinned to). If it still names the old profile, the
      process did not re-bind: restart it.

PET-132 ships the Petasos half of the eventual no-restart path: an
operator-trusted re-bind worker that re-pins the resolution, resets the
armed/reload caches, and hot-applies the new profile's config. It is **dormant**
until Hermes fires a trusted profile-change signal that names the new profile
home out-of-band from anything the guarded agent can write (the re-bind never
re-reads the agent-writable `active_profile` pointer, preserving the section 6
boundary). Until that Hermes-side signal exists, the restart contract above is
the only supported way to change a security-bearing gateway's profile. When the
re-bind does fire, the pipeline/guard config is process-wide, so it applies to
every session the process hosts; in-flight sessions see the new shared config at
their next tool call (the swap does not drain them first).

PET-147 status: the PET-132 re-bind worker is now proven **host-callable
end-to-end**, not just call-correct. An in-process host-stub test
(`test_hermes_signal_triggers_rebind_end_to_end`) registers the plugin against a
fake Hermes ctx, captures the `on_profile_change` handler the way a real host
would, fires it, and asserts the live pipeline actually retargets (fail_mode and
egress set move to the new profile, and the binding line re-emits naming it). A
companion test (`test_unregistered_host_still_degrades_to_restart`) proves the
inverse at the tool-call level: a host that rejects the hook leaves no handler to
fire, so the pipeline stays pinned to the boot profile until a restart. This
closes the Petasos-side verification gap; it does **not** make live re-bind work
in production. The sole remaining gate is the external, operator-trusted Hermes
emitter that fires `on_profile_change` from the trusted swap path (never from the
agent-writable `active_profile`); until Hermes ships it, the restart contract
above stays the only supported way to change a security-bearing gateway's
profile. The assumed signal contract is pinned (`on_profile_change(profile_name,
profile_home)`, `profile_home` an existing absolute dir); reconciling it to the
real Hermes name and payload is tracked on the Hermes-side work item.

### The source-taint egress fence is verbatim, defense-in-depth (PET-134)

`source_taint_namespaces` adds a content-agnostic egress fence: once a tool in a
declared source namespace (for example a banking or health connector) returns
content, a **normalized substring** of that text is blocked from leaving again
through any `egress_sink_tools` tool, even when it carries no PII pattern. The
match folds case, zero-width, and homoglyph variants, so a trivially obfuscated
copy is still caught; a paraphrase or re-encoding is not (see the verbatim bullet
below). It closes the
structural hole the PII matcher cannot reach: a non-PII balance, amount, or
merchant relayed off-box. It is **off by default** (empty
`source_taint_namespaces`); the Configuration guide covers the two operator levers
(`source_taint_namespaces` and `taint_min_span_length`).

Understand its boundary before relying on it:

- **It is a verbatim, source-to-off-box guarantee, not a dataflow tracer.** The
  fence matches a normalized exact substring of what the source returned. A copy
  the model paraphrases, summarizes, base64-encodes, or otherwise transforms
  before the egress call is **not** caught. Treat it as defense-in-depth against a
  direct relay, not a complete exfiltration control.
- **It does not intercept the model call.** There is no `pre_llm_call` hook, so
  tainted content can still reach the language model. Closing the inference-time
  leak is a configuration concern (run a local model so the content never leaves
  the box), not something this fence does.
- **It is not a replacement for local inference or network isolation.** It rides
  on the same tool-call boundary as the rest of the guard. An agent with an
  unsanctioned network path (a shell, or an HTTP tool that is not listed in
  `egress_sink_tools`) is outside its reach. Pair it with the deployment posture
  in this section, do not substitute it for that posture.
- **The enabling field must survive the model switcher (see Vector A / PET-115).**
  The fence is off whenever `source_taint_namespaces` is empty, and the Hermes
  Desktop model switcher wipes the `petasos:` config section, which empties the
  field and silently disarms the fence: the same per-field config-wipe footgun
  every `petasos:` setting shares. Confirm the field is still present after a model
  switch before trusting the fence.

---

*Companion docs: [hermes-desktop.md](hermes-desktop.md) (step-by-step Hermes
Desktop deployment) · [hermes-desktop-footguns.md](../platform/hermes-desktop-footguns.md)
(Windows platform caveats).*
