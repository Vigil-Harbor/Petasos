# Gavin banking egress fencing

How to make "financial data must not egress the box" true for Gavin's Hermes
banking profile, and what that guarantee does and does not cover. The guarantee
is primarily architectural (local-only inference); Petasos is the enforcement
point on the agent-to-off-box-tool boundary, plus defense-in-depth and audit.

> **Before you start:** read the [deployment hardening checklist](hardening.md)
> for where Petasos sits in your security model (it is a detection layer, not a
> boundary), and [Deploying Petasos on Hermes Desktop](hermes-desktop.md) for
> the base install, the `petasos:` config section, and the profile config path.
> This note adds only the banking-profile specifics on top of that baseline.

**Ticket:** PET-133 (decisions D3, D4 of the Gavin Banking Observability work)  
**Petasos version:** 0.1.2+  
**Profile:** the active Hermes profile Gavin runs under (for example `gibson`)

---

## 1. The guarantee and its honest limits

The primary guarantee is architectural, not content inspection:

- **Local inference (D3).** Gavin's model runs on the box (LM Studio, llama.cpp,
  or a local OpenAI-compatible server), so the inference call itself never ships
  context off-box. This is the load-bearing control; sections 2 and 5 make it a
  checkable hard gate.
- **The bank MCP is reachable only as a local stdio subprocess**, with no inbound
  webhook, so the only way bank data leaves is through a tool the agent calls.
- **Petasos fences that agent-to-off-box-tool boundary** and provides the audit
  trail.

**Honest limit (read this before you rely on it).** Petasos blocks PII findings
on egress sinks, and the source-taint fence (section 4) blocks verbatim relay of
content pulled from the bank. But most banking *figures* (balances, amounts,
merchant names) are not Presidio entities, so the PII-egress block alone does not
stop them. Petasos here is defense-in-depth, audit, and the agent-to-off-box
enforcement point; it is not a content-aware "no figure leaves" guarantee. The
PET-134 taint wiring (section 4) narrows the gap for content relayed verbatim
from a bank tool, but a model that paraphrases a balance into a new sentence and
hands it to an egress tool is outside what the fence can see. The architectural
controls above, not Petasos content matching, are what make the box safe.

---

## 2. D3: local inference is a hard gate

The leak Petasos cannot intercept is the LLM inference call. The plugin registers
`pre_tool_call` / `post_tool_call` / `on_session_start`, never `pre_llm_call`, so
once bank data is in Gavin's context a *cloud* model would transmit it off-box on
the next turn, a path no hook can stop. D3 closes this by configuration: Gavin's
profile must point at a local inference endpoint. A cloud `model:` is a release
blocker.

That requirement is enforced by a checkable predicate so a profile edit cannot
silently reopen it. Gavin's profile CI (and your own pre-flight check) runs:

```python
from petasos.profile_lint import is_local_inference_endpoint

# provider + base_url come from the profile's model: section.
assert is_local_inference_endpoint(provider, base_url), (
    "D3 blocker: Gavin's inference endpoint is not local"
)
```

The predicate is fail-secure: anything it cannot positively recognize as the
local box returns `False`. It is imported module-qualified
(`from petasos.profile_lint import ...`); it is intentionally not on the package's
top-level `petasos` export surface. See section 6 for the exact `base_url` forms
it accepts and the ones it rejects by design.

---

## 3. D4: egress-sink classification

Petasos blocks PII findings at HIGH or worse only on tools classified as egress
sinks; internal tools are exempt by design. For Gavin:

- **Every off-box tool Gavin can reach is an egress sink.** The Vigil MCP
  outbound / ingest tools, any `web_fetch` / `http` / `fetch`, and any messaging
  `*_send` go in `egress_sink_tools`, by their full single-underscore wire name
  (see the canonicalization note in `hermes-desktop.md`).
- **The `mcp_bank_*` tools are sources, never sinks.** The agent pulls data in
  through them, so they are absent from `egress_sink_tools`. Listing a bank tool
  as a sink would be a miscategorization; the regression
  `test_bank_pii_blocked_to_egress_sink` pins that a bank source tool is not
  blocked while a real sink is.
- **Presidio is enabled with `anonymize: true`**, so the classic high-severity
  identifiers (full account / routing number, SSN, card) are blocked or redacted
  on egress.

This classification is operator config in the profile, not a code change. No
banking-specific tool names ship in the Petasos library defaults; they live only
in Gavin's profile, this note, and the test fixtures.

---

## 4. Source-taint wiring for `mcp_bank_`

The content-agnostic provenance fence (PET-134) blocks content returned by a tool
in a declared source namespace from leaving verbatim through an egress sink, even
when it carries no PII span. Wire it for Gavin in the `petasos:` section:

```yaml
  source_taint_namespaces: ["mcp_bank_"]
  taint_min_span_length: 12
```

`source_taint_namespaces` is matched as a single-underscore wire prefix against a
producing tool's canonical name, so `mcp_bank_list_accounts`,
`mcp_bank_query_transactions`, and their case / CamelCase / `_tool` variants all
taint. `taint_min_span_length` (default 12) is the false-positive floor: a
captured span shorter than this is never stored, so a low-entropy value like
`$5.00` cannot poison every later argument. Leave it at the default unless you see
false positives (raise it) or want broader coverage (lower it). The regression
`test_tainted_nonpii_blocked_to_egress_sink` already proves a non-PII
`$4,000 at Whole Foods` string captured from `mcp_bank_list_accounts` is blocked
when relayed to `send_email`.

---

## 5. Example compliant profile

A minimal Gavin-shaped `model:` plus `petasos:` block. Edit the **profile's**
`config.yaml`, not the root one (Hermes v0.16+):

```text
# Windows: %LOCALAPPDATA%\hermes\profiles\gibson\config.yaml
# macOS:   ~/.hermes/profiles/gibson/config.yaml
```

```yaml
# Local inference endpoint (D3 hard gate). is_local_inference_endpoint() must
# pass for this provider + base_url.
model:
  provider: "lmstudio"
  base_url: "http://127.0.0.1:1234/v1"

petasos:
  enabled: true
  fail_mode: "closed"
  host_id: "gavin-banking"

  # D4: PII on egress is blocked or redacted.
  anonymize: true
  pii_entities: ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN", "US_BANK_NUMBER"]
  redaction_mode: "hash"

  # D4: every off-box tool Gavin can reach is an egress sink. Bank tools are
  # sources (pulled in), so they are deliberately NOT listed here.
  egress_sink_tools:
    - send_email
    - send_message
    - http_request
    - send_webhook
    - mcp_vigil_harbor_memory_ingest

  # PET-134: content from the bank namespace may not leave verbatim.
  source_taint_namespaces: ["mcp_bank_"]
  taint_min_span_length: 12
```

After applying it, run the section 2 lint against the live `model:` values and do
a full app restart (plugin discovery runs at startup; see `hermes-desktop.md`).

---

## 6. Local-endpoint troubleshooting

`is_local_inference_endpoint` is fail-secure, so a malformed local endpoint reads
as "not local" and blocks the release. Write `base_url` as one of:

```text
http://127.0.0.1:<port>
http://localhost:<port>
```

The rules behind that, and the traps the predicate rejects by design:

- **The `http://` (or `https://`) scheme is mandatory.** A bare `localhost:1234`
  or `127.0.0.1:1234` parses with no host (the token before the first `:` is read
  as the URL scheme), so it returns `False`. Always write the scheme.
- **Never `127.1`.** IPv4 dotted-shorthand is not a valid address literal, so it
  is rejected. Write the full `127.0.0.1`.
- **Never a zero-padded octet** (`127.0.0.01`, `127.000.000.001`). Leading zeros
  are rejected for octal ambiguity. Write the canonical `127.0.0.1`.
- **Never `0.0.0.0` or a LAN address** (`10.x`, `172.16-31.x`, `192.168.x`). A
  server may *bind* `0.0.0.0`, but the profile `base_url` must still name the
  loopback (`127.0.0.1` or `localhost`); `0.0.0.0` and LAN addresses fail by
  design, because they are reachable from off the box.
- **An unlisted local runtime needs an explicit loopback `base_url`.** The
  provider-only fallback recognizes a fixed allowlist (`lmstudio`, `llama.cpp`,
  `llamacpp`, `ollama`, `local`, `localai`). A legitimate but unlisted runtime
  (`vllm`, `text-generation-webui`, `koboldcpp`, `tabbyapi`) returns `False` on
  the provider name alone; set the explicit loopback `base_url` and it passes
  (`base_url` is authoritative over `provider`).

---

## 7. Windows model-switcher caveat

On Windows, the Hermes Desktop UI model switcher rewrites the `model:` section and
has, on some builds, wiped the top-level `petasos:` section with it (PET-115). If
`petasos:` is gone, **both the egress fence and the taint fence are off**, and
bank data can leave through any tool. Treat every model switch as suspect:

1. **Detect.** After any model switch, re-run the section 2 lint against the new
   `model:` values, and confirm the `petasos:` section is still present in the
   live profile `config.yaml`:

   ```bash
   # Git Bash
   grep -n '^petasos:' "$LOCALAPPDATA/hermes/profiles/gibson/config.yaml"
   ```

   ```powershell
   # PowerShell
   Select-String -Pattern '^petasos:' "$env:LOCALAPPDATA\hermes\profiles\gibson\config.yaml"
   ```

   No match means the section was wiped.

2. **Recover.** Re-apply the section 5 snippet (`petasos:` plus a local `model:`),
   then do a full app restart so the plugin reloads it.

3. **Do not resume until recovered.** If `petasos:` is absent after a switch, the
   egress fence and the `mcp_bank_` taint fence are both off; bank data can egress
   unblocked. Re-apply the snippet and restart before letting Gavin run any
   banking task.
