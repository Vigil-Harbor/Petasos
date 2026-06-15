# Scanner reference

Petasos inspects content with a set of pluggable *scanners*. Each one looks at
text and returns findings; the pipeline merges those findings, tracks them per
session, and decides what to do. This page explains what each scanner detects,
how it works, when it runs, and what you get by installing its optional extra.

Detection ships free and keyless. The zero-dependency syntactic scanner is
always present. The three machine-learning backends are *dependency-gated*: they
are normal pip extras you opt into (`pip install petasos[...]`), not paid or
licensed tiers. If you do not install an extra, that scanner is simply absent and
the rest of the pipeline runs without it.

> Verified against source at commit `770401e`. Every count and list on this page
> is pinned to live source by `tests/test_docs_usage_consistency.py`, so the
> numbers below cannot drift away from the code without a test going red.

## Where each scanner runs

The pipeline processes one piece of text through a fixed order of stages. The
"when it runs" line in each scanner section below refers to this order:

1. **Normalize**: NFKC folding, zero-width stripping, homoglyph mapping, and
   right-to-left override handling, so look-alike and hidden-character tricks are
   undone before anything is checked.
2. **Syntactic pre-filter**: the always-on `MinimalScanner`, zero dependencies,
   runs on every scan.
3. **Fan-out to the configured machine-learning scanners** (`LlmGuardScanner`,
   `LlamaFirewallScanner`, `PresidioScanner`), gathered concurrently.
4. **Merge and dedup** the findings from all scanners.
5. **Frequency update**, then **escalation check** against the session's running
   risk score.
6. **Anonymize** (Presidio), if personal data was found and anonymization is on.
7. **Audit**, then **alerting**.

A scanner that is not installed is skipped at the fan-out stage. The syntactic
pre-filter at stage 2 always runs regardless of which extras are present.

## MinimalScanner (always ships, zero dependencies)

`MinimalScanner` is the syntactic pre-filter. It needs no machine-learning
dependencies and runs on every scan as stage 2 above, holding to a sub-5ms
budget so it can sit in front of everything else.

**What it detects.** A taxonomy of 22 rules grouped into 5 families:

<!-- petasos-doc-assert: rule_taxonomy_total=22 -->

- **injection** (8 rules): prompt-injection phrasings such as "ignore all
  previous instructions", instruction delimiters, and system-prompt overrides.
- **role-switch** (2 rules): attempts to reassign the assistant's role or claim
  new capabilities.
- **structural** (3 rules): oversized payloads, excessive nesting depth, and raw
  binary content.
- **encoding** (4 rules): base64-in-text, invisible characters, homoglyph
  substitution, and right-to-left override abuse.
- **command** (5 rules): shell-command patterns such as pipe-to-shell,
  fetch-and-execute, decode-and-execute, and destructive recursive deletes.

<!-- petasos-doc-assert: rule_family.injection=8 rule_family.role_switch=2 rule_family.structural=3 rule_family.encoding=4 rule_family.command=5 -->

**How it works.**

- *Anchor gates.* Before running the full injection or command batteries, the
  scanner checks a cheap necessary-condition anchor (a small substring superset
  of every pattern in the family). If the anchor is absent the whole battery is
  skipped, which is what keeps the syntactic pass inside its sub-5ms budget on
  ordinary text.
- *Decode-and-rescan.* base64, hex, and ROT13 blobs are decoded and the
  plaintext is re-run through the injection patterns. An "ignore all previous
  instructions" wrapped in base64 is therefore caught at full injection severity
  instead of slipping through as a low-priority encoding flag. Decoding is
  bounded by size, count, and depth caps so it cannot be turned into a denial of
  service, and it only ever raises a flag on a real injection in the decoded
  text.
- *Suppressibility.* A profile can suppress the **command** and **encoding**
  families when they are noisy for its use case (for example, the
  `code_generation` profile, which legitimately handles shell snippets). The
  **injection**, **role-switch**, and **structural** families are hardcoded as
  unsuppressible: no profile can switch them off.

**When it runs.** Stage 2, on every scan, always.

**What an extra adds.** Nothing. `MinimalScanner` is part of the base install
(`pip install petasos`) and has no optional dependency.

## LlmGuardScanner (extra: `llm-guard`)

`LlmGuardScanner` wraps the [LLM Guard](https://github.com/protectai/llm-guard)
library to add model-backed prompt-injection and content detection on top of the
syntactic rules.

**What it detects.** LLM Guard's scanner suite (model-scored prompt-injection and
related content checks), contributing its findings to the merge stage.

**How it works.** The backend is absent unless you install the extra
(`pip install petasos[llm-guard]`); until then the scanner reports itself
unavailable rather than failing a scan. The underlying models load lazily on
first use, with a bounded retry budget (one attempt plus two retries) behind a
stdio and weakref shield so that structlog's weakref registration cannot crash
hosts with slots-only stdio (Hermes Desktop is the motivating case).

The scanner distinguishes two unavailable states for operators: **absent** (the
`llm-guard` extra is not installed) versus **load-failed** (the extra is
installed but the model could not be loaded). The first is a packaging choice;
the second is something to investigate.

**When it runs.** Stage 3, in the machine-learning fan-out, only when installed
and enabled.

**What the extra adds.** `pip install petasos[llm-guard]` installs LLM Guard and
its model dependencies and makes this scanner available.

## LlamaFirewallScanner (extra: `llamafirewall`)

`LlamaFirewallScanner` wraps Meta's
[LlamaFirewall](https://github.com/meta-llama/PurpleLlama) and exposes three
named components.

**What it detects.** Three components, each mapped to a finding category and a
severity:

<!-- petasos-doc-assert: llamafirewall_components=prompt_guard,alignment_check,code_shield -->

- `prompt_guard`: prompt-injection detection, category `injection`, severity
  HIGH.
- `alignment_check`: agent-alignment auditing, category `alignment`, severity
  HIGH.
- `code_shield`: unsafe-code detection, category `unsafe_code`, severity MEDIUM.

**How it works.** The live path may need a Hugging Face token and model
prerequisites to download the underlying models. The first scan triggers a model
load and reports a short "warming up" status while that happens. A stdin guard
intercepts the interactive prompt some model loaders raise in a non-interactive
host, turning it into an actionable message instead of a hang.

**When it runs.** Stage 3, in the machine-learning fan-out, only when installed
and enabled.

**What the extra adds.** `pip install petasos[llamafirewall]` installs
LlamaFirewall and makes the three components above available.

**Setting up the gated PromptGuard 2 model.** PromptGuard 2
(`meta-llama/Llama-Prompt-Guard-2-86M`) is a *gated* model on Hugging Face, so
installing the extra is not enough on its own. Before the first live scan:

1. Request access on the model page,
   [huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M),
   while signed in, and accept Meta's license. Approval is usually quick.
2. Authenticate locally so the download can use that grant: run
   `huggingface-cli login`, or set `HF_TOKEN` to a read token from your account.
   Confirm with `huggingface-cli whoami`.
3. If you run the prompt-guard scanner in parallel, set
   `export TOKENIZERS_PARALLELISM=true`.

The first scan then downloads the model into your Hugging Face cache
(`~/.cache/huggingface`, or `HF_HOME` if set). Until access is granted and a
token is present, the scanner fails fast with an actionable message rather than
hanging on the loader's interactive login prompt. `alignment_check` and
`code_shield` are opt-in and carry their own model and runtime prerequisites.

## PresidioScanner (extra: `presidio`)

`PresidioScanner` wraps [Microsoft Presidio](https://github.com/microsoft/presidio)
for personally identifiable information (PII) detection, and it is also the
backend for the anonymization stage.

**What it detects.** A curated default band of 10 entity types, chosen to be the
security-relevant CRITICAL and HIGH classes:

<!-- petasos-doc-assert: presidio_default=CREDIT_CARD,IBAN_CODE,US_SSN,US_BANK_NUMBER,CRYPTO,EMAIL_ADDRESS,PHONE_NUMBER,US_DRIVER_LICENSE,US_PASSPORT,IP_ADDRESS -->

- CRITICAL: `CREDIT_CARD`, `IBAN_CODE`, `US_SSN`, `US_BANK_NUMBER`, `CRYPTO`.
- HIGH: `EMAIL_ADDRESS`, `PHONE_NUMBER`, `US_DRIVER_LICENSE`, `US_PASSPORT`,
  `IP_ADDRESS`.

Five further entity types are **opt-in by design**, not part of the default:

<!-- petasos-doc-assert: presidio_opt_in=PERSON,LOCATION,DATE_TIME,NRP,URL -->

`PERSON`, `LOCATION`, `DATE_TIME`, `NRP`, and `URL` are left out of the default
because they misfire on technical text: file paths, code, version numbers, and
hostnames trip them constantly. You can add any of them back when your data
warrants it, but the default set deliberately avoids that noise. The opt-in set
is never presented as the default.

**How it works.** Detection is tuned by a small group of config fields, and a
separate anonymization stage acts on what is found:

- `presidio_entities`: replace the detected entity list wholesale.
- `presidio_entities_extra`: add entity types back on top of the curated default
  (for example, opt `URL` back in) without discarding the rest.
- `presidio_score_threshold`: the confidence floor a match must clear before it
  is reported.
- `anonymize`: whether the anonymization stage runs at all.
- `pii_entities`: narrow which detected types are actually hidden at the
  anonymize step (detection scope is separate).
- `redaction_mode`: how a hidden value is rewritten (redact, replace, hash, or
  mask).
- `hash_key`: the secret key used when `redaction_mode` is `hash`.

See [the configuration guide](configuration.md) for the full walkthrough of these
fields.

**When it runs.** Detection happens at stage 3 (the fan-out) when installed and
enabled; anonymization happens later, at stage 6, only when PII was found and
`anonymize` is on.

**What the extra adds.** `pip install petasos[presidio]` installs Presidio and
its language model and makes both PII detection and anonymization available.
