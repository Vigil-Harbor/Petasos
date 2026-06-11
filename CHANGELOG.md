# Changelog

All notable changes to Petasos are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Fixed
- **Scanner init logs now tell the truth** — init surfaces (reference plugin, dashboard) log "backend verified" or "backend missing" based on a real availability probe instead of claiming "loaded" on instantiation (PET-87)
- **Health endpoint reflects scan-time reality** — `scanner_health()` status enum corrected to `healthy | degraded | circuit_open | unavailable` with a `last_error` field; scanners whose backend is absent report `unavailable` instead of `healthy` (PET-87)
- **LlamaFirewall no longer hangs on missing HF token** — fail-fast prerequisite check and stdin tripwire prevent upstream's interactive `huggingface_hub.login()` from blocking the event loop (PET-87)

## [0.1.0] — 2026-06-01

First public release. All features ship free and keyless.

### Added
- **Pipeline orchestrator** — 12-stage async pipeline (`normalize → scan → merge → decide`) with never-throws invariant and three fail-mode policies (open / closed / degraded)
- **Scanner protocol** — pluggable `Scanner` interface with four backends:
  - `MinimalScanner` — 17 regex rules, zero dependencies, <5ms
  - `LlmGuardScanner` — DeBERTa-v3 prompt injection + toxicity (optional extra)
  - `LlamaFirewallScanner` — Meta PromptGuard 2 + CodeShield (optional extra)
  - `PresidioScanner` — PII detection + anonymization with HMAC hashing (optional extra)
- **Input normalization** — NFKC, zero-width stripping, combining mark removal, homoglyph mapping (44 confusables), RTL override detection
- **Frequency tracking** — per-session exponential decay scoring, rolling window, rate limiting, HMAC-SHA256 session token binding
- **3-tier escalation** — configurable thresholds with hardcoded Tier 3 floor (30.0); standalone safety net on ≥3 CRITICAL findings
- **Tool call guard** — 8-step evaluation with NFKC + homoglyph + casefold tool name normalization, alias resolution, parameter scanning, exempt-with-scan
- **Profiles** — 5 frozen built-in profiles (general, customer_service, code_generation, research, admin), custom registration, severity override floors, unsuppressible rule protection
- **Audit trails** — verbosity-gated event recording with monotonic sequencing, secret redaction, exception-isolated callbacks
- **Alert rules** — 5 built-in rules with per-rule cooldowns, dual rate limiting, per-session contribution caps, critical alert caps
- **Configuration** — single frozen `PetasosConfig` dataclass, JSON-serializable, strict bool coercion, construction-time type validation
- **License machinery** — Ed25519 JWT validation with key-fingerprint pinning (parked for future supporter/compliance recognition; does not gate features)
- **Security hardening** — 60 red-team findings resolved across 12 domains (see `docs/specs/` for individual remediation specs)

[0.1.0]: https://github.com/Vigil-Harbor/Petasos/releases/tag/v0.1.0
