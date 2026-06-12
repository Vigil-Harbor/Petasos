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

## 3. Secrets

Two secrets, both environment-variable-first, never committed config:

| Secret | Purpose | Handling |
|---|---|---|
| `PETASOS_SESSION_SECRET` | HMAC session binding — prevents session spoofing (FREQ-03) | base64 in env; decoded at dashboard init (`petasos/console/hermes/plugin_api.py:65-73`). Invalid base64 → a warning is logged and **session binding is silently disabled** — watch for that log line. |
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
      [hermes-desktop.md §2](hermes-desktop.md) for one-liners).
- [ ] If you set `PETASOS_SESSION_SECRET`, also configure `host_id` —
      the pipeline requires it when a session secret is present
      (`petasos/pipeline.py:225-226`).
- [ ] Grep your logs once after deploy for the invalid-base64 warning;
      binding that silently disabled is worse than binding you never
      configured.

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

---

*Companion docs: [hermes-desktop.md](hermes-desktop.md) (step-by-step Hermes
Desktop deployment) · [hermes-desktop-footguns.md](../platform/hermes-desktop-footguns.md)
(Windows platform caveats).*
