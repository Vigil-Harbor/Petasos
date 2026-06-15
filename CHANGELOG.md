# Changelog

All notable changes to Petasos are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

_Nothing yet._

## [0.1.0] - 2026-06-14

First public release. Every feature ships free and keyless: no license key, no tiers, no gate.

### Added

- **Pipeline orchestrator**: a multi-stage async pipeline (`normalize → scan → merge → decide → session intelligence`) with a hard never-throws invariant: every outcome, including total scanner failure, returns in a structured `PipelineResult`. Three fail-mode policies: `degraded` (default: block on partial ML failure), `closed` (block on any failure), `open` (pass through).
- **Scanner protocol + four backends**: a pluggable `Scanner` interface:
  - `MinimalScanner`: 22 regex rules (injection, role-switch, structural, encoding, obfuscated destructive-command), zero dependencies, always on, <5ms, the safety floor
  - `LlmGuardScanner`: DeBERTa-v3 prompt injection + toxicity (optional extra)
  - `LlamaFirewallScanner`: Meta PromptGuard 2 + AlignmentCheck + CodeShield, per-component toggles (optional extra)
  - `PresidioScanner`: PII detection + anonymization with redact / mask / replace / HMAC-SHA256 hash (optional extra)
- **Input normalization**: NFKC, zero-width / invisible-character stripping, combining-mark removal, 44-confusable homoglyph mapping, RTL-override detection, leet-speak folding, and decode-and-rescan of base64 / hex / ROT13 payloads
- **Frequency tracking**: per-session exponential-decay scoring, rolling window, rate limiting, HMAC-SHA256 session-token binding, tombstoned terminations
- **3-tier escalation**: configurable thresholds with a hardcoded Tier-3 floor (30.0) and a standalone safety net on ≥3 CRITICAL findings; extends across sub-agent delegation trees via lineage escalation and a fan-out budget
- **Tool call guard**: tool-name canonicalization (NFKC + homoglyph + casefold + namespace / CamelCase / `_tool` folding), alias resolution, parameter scanning, and an egress-scoped PII policy that blocks data-exfiltration sinks without blocking the agent's own local writes
- **Profiles**: 5 frozen, self-describing built-ins (general, customer_service, code_generation, research, admin) plus custom registration, severity-override floors, and an unsuppressible injection/structural rule floor
- **Audit trails**: verbosity-gated, monotonically sequenced, secret-redacting, exception-isolated event recording
- **Alert rules**: 5 built-in rules with per-rule cooldowns, dual rate limiting, per-session contribution caps, and a critical-alert cap
- **Console dashboard** (`petasos[console]`): a FastAPI dashboard that runs standalone or as a Hermes Desktop plugin, with four surfaces (Observability, Scan Playground, Config Editor, About), live SSE updates, an Equipped/Unequipped master toggle that arms/disarms enforcement on running sessions (with live multi-tab sync), collapsible config sections carrying plain-language help on every field, and Hermes v0.16+ profile-aware config resolution
- **PII detection scoping**: a curated default entity band (cards, SSNs, bank/IBAN, crypto, email, phone, passport, license, IP), opt-in noisy classes, per-profile additive entities, and a tunable score threshold
- **Configuration**: a single frozen, JSON-serializable `PetasosConfig` with strict bool coercion and construction-time validation; every field exposed for frontend binding
- **License machinery (parked)**: Ed25519 JWT validation with key-fingerprint pinning, preserved for future supporter/compliance recognition; does not gate any feature
- **Deployment**: a reference Hermes plugin, a config-path resolver for v0.15 / v0.16+ layouts, a `verify.py` deployment checker, and an OS-boundary hardening checklist

### Security

- **60 red-team findings resolved** across 12 domains: normalization bypasses, config coercion, session spoofing, guard evasion, pipeline severity handling, profile suppression, audit secret-leak, and alert starvation. Per-finding remediation specs live in `docs/specs/`.
- **Tool-name canonicalization parity**: enforcement and classification share one canonical primitive, closing case / homoglyph / namespace / CamelCase / `_tool`-suffix variant-named egress bypasses
- **PII-egress hardening**: egress-scoped guard blocking, corrected ordinal severity ranking (a lone CRITICAL now blocks), and a parse-time PII-entity vocabulary guard

[Unreleased]: https://github.com/Vigil-Harbor/Petasos/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Vigil-Harbor/Petasos/releases/tag/v0.1.0
