# PET-14 — Red-Team Security Review

**Status:** Backlog → Ready for scoping  
**Priority:** High  
**Parent:** PET-11 (Integration Testing + Performance Benchmarks)  
**Blocked by:** PET-10 (JWT + Premium Wiring) — all premium code must be landed before review  
**Blocks:** PET-12 (Wiki + Docs + PyPI Release) — no public release until red-team pass  

---

## Purpose

Petasos is a security plugin that will be released publicly. Before we ship a library whose entire value proposition is "we stop attacks," we need to prove it can survive attacks aimed at itself. PET-14 scopes a security-grade code review and adversarial testing pass across the full Petasos codebase.

This is not a functional test pass (PET-11 covers that). This is an offensive assessment: find exploits, document every catch, and produce a validation inventory that proves the library does what it claims.

## Threat Model

### In scope — external attacks on the agent

Petasos sits between untrusted input and the agent's tool execution layer. The threat model is an adversary who controls message content and attempts to:

1. **Bypass detection** — craft input that evades the syntactic pre-filter, ML scanners, or the pipeline's merge/dedup logic to deliver a payload unmarked.
2. **Degrade the pipeline** — trigger scanner failures to force fail-mode fallback, then exploit the degraded state (especially `fail_mode="open"`).
3. **Manipulate frequency/escalation** — game session scoring to avoid tier escalation, or trigger false-positive escalation against legitimate users.
4. **Circumvent the ToolCallGuard** — smuggle tool parameters past the guard via namespace tricks, alias collisions, or parameter encoding.
5. **Forge or replay license JWTs** — bypass premium gating, elevate tier, or crash the validator.
6. **Exploit normalization gaps** — use Unicode sequences, homoglyphs, RTL overrides, or encoding tricks that survive normalization but evade regex matching downstream.
7. **Poison configuration** — inject or mutate `PetasosConfig` at runtime to disable scanners, lower thresholds, or suppress alerts.
8. **Exfiltrate via audit/alert callbacks** — if an attacker can influence callback payloads (e.g., finding text reflected verbatim), abuse the audit or alert emission surface.

### Out of scope — internal agent misbehavior

The threat of the agent itself acting maliciously is Hermes's side of the contract. Petasos guards the perimeter; it does not police the agent's own reasoning. If red-team reviewers encounter internal-agent issues they should flag them as informational findings, not primary targets.

### OWASP alignment

This review maps findings to the **OWASP Top 10 for Agentic Applications (2026)** where applicable, particularly:

- **ASI01 — Agent Goal Hijack:** Petasos's syntactic pre-filter and ML scanners are the defense layer. Red-team should attempt to hijack through content that bypasses them.
- **ASI02 — Tool Misuse & Exploitation:** ToolCallGuard is the defense. Red-team should attempt parameter smuggling and namespace exploitation.
- **ASI07 — Guardrail Bypass:** The pipeline itself is a guardrail. This is the primary attack surface.

---

## Methodology

### Model diversity requirement

Reviewers must use a **different model family** than the one used to write the code. The Plane ticket specifies GPT-5.5 via Cursor. The rationale: same-model review inherits the same blind spots; cross-model framing surfaces assumptions the author model wouldn't question.

### Reviewer agents — rotatable lenses

Deploy 3–6 reviewer agents, each with a distinct lens. Recommended set:

| # | Lens | Focus | Key questions |
|---|------|-------|---------------|
| 1 | **Convention & correctness** | Code quality, type safety, contract adherence | Does the code match the spec? Are types sound? Are invariants enforced? |
| 2 | **Edge cases & fault tolerance** | Boundary conditions, error paths, concurrency | What happens at 0, 1, MAX_INT? What if two scanners timeout simultaneously? What if `asyncio.gather` is cancelled mid-flight? |
| 3 | **Security vulnerability** | Classic vulnerability classes adapted to this domain | Regex catastrophic backtracking (ReDoS)? Deserialization of untrusted config? Unsafe `eval`/`exec`? Timing side-channels in JWT validation? |
| 4 | **Exploitable processes** | Pipeline-level attack chains, multi-step exploits | Can an attacker chain a normalization gap + scanner timeout + fail-open to deliver a payload? Can frequency state be poisoned across sessions? |
| 5 | **Evasion & bypass** | Adversarial input crafting against detection | Homoglyph substitutions the table misses? Invisible characters not in the strip list? Payload fragmentation across multiple messages? Encoding tricks (base64 in parameters, nested JSON)? |
| 6 | **Client/UX watchdog** | Consumer-facing contract, error messages, fail states | Does degraded mode communicate clearly? Can a false positive lock out a legitimate user with no recovery path? Do error messages leak internal state? |

Each lens produces a findings list ranked by severity (critical / high / medium / low / informational).

### Attack corpus

Build a structured adversarial test corpus organized by attack category:

- **Prompt injection variants** — the 17 syntactic patterns plus known evasion techniques (case mixing, Unicode substitution, payload splitting, instruction-delimiter injection, multi-language switching).
- **Normalization bypass** — characters outside the homoglyph table, combining marks that alter glyph appearance post-NFKC, RTL sequences that reorder display but not byte order.
- **Scanner-specific evasion** — payloads tuned to the confidence thresholds of LLM Guard (0.85 default), LlamaFirewall PromptGuard, and Presidio entity recognition.
- **Pipeline state attacks** — rapid-fire sequences designed to trigger race conditions in `asyncio.gather`, frequency tracker manipulation, session ID spoofing for cross-session burst detection.
- **JWT attacks** — expired tokens, `alg: none`, key confusion (RSA key as HMAC secret), oversized payloads, invisible character injection in token string, clock-skew exploitation.
- **Configuration mutation** — attempts to modify frozen dataclasses, mutate `MappingProxyType` exports, override `__setattr__` on frozen instances.
- **Tool parameter smuggling** — nested JSON in tool parameters containing injection payloads, namespace prefixes that alias to dangerous tools, parameter values that exploit the recursive pipeline scan.

### Documentation requirement

**Every finding gets documented.** Both successful exploits and blocked attempts. Blocked attempts are validation evidence — they prove the pipeline works. The output is a findings ledger with:

- Finding ID (sequential, e.g., `RT-001`)
- Lens that discovered it
- Severity (critical / high / medium / low / informational)
- OWASP mapping (if applicable)
- Attack vector (what the adversary does)
- Expected behavior (what Petasos should do)
- Actual behavior (what happened)
- Affected file(s) and line(s)
- Remediation (if exploit succeeded)
- Status (open / remediated / accepted-risk)

---

## Scope — files under review

The full `petasos/` package (19 Python files at current HEAD `44639fe`):

| Module | File | Security surface |
|--------|------|-----------------|
| Types | `_types.py` | Protocol contracts, frozen dataclass integrity |
| Normalization | `normalize.py` | Homoglyph table completeness, invisible char coverage, NFKC edge cases |
| MinimalScanner | `scanners/minimal.py` | 17 regex rules — ReDoS risk, evasion via encoding, pattern completeness |
| LLM Guard | `scanners/llm_guard.py` | Lazy-load safety, threshold bypass, error isolation |
| LlamaFirewall | `scanners/llama_firewall.py` | Lazy-load safety, async bridging, component isolation |
| Presidio | `scanners/presidio.py` | Entity coverage, anonymization operator correctness, HMAC determinism |
| Pipeline | `pipeline.py` | Orchestration integrity, fail-mode enforcement, finding merge/dedup, concurrency |
| Config | `config.py` | Frozen enforcement, deserialization safety, validation completeness |
| Frequency | `premium/frequency.py` | Decay correctness, LRU eviction under pressure, rate limiting |
| Escalation | `premium/escalation.py` | Tier 3 floor enforcement (cannot be disabled), threshold manipulation |
| Profiles | `premium/profiles/__init__.py` | Frozen built-in profiles, custom profile isolation, merge safety |
| Guard | `premium/guard.py` | Tool name normalization completeness, namespace stripping, alias collisions |
| Audit | `premium/audit.py` | Sequence number monotonicity, TTL pruning, callback safety |
| Alerting | `premium/alerting.py` | Rate limiting correctness, critical exemption bypass, ring buffer integrity |
| License | `premium/license.py` | JWT algorithm restriction, clock skew, invisible char stripping, key handling |

Plus: test files (for test-quality assessment), `pyproject.toml` (for dependency pinning review), and the bundled public key in `premium/_keys/`.

---

## Decisions Carried Forward

1. **Cross-model review is mandatory.** The code was written by Claude; the red-team review uses GPT-5.5 (or another non-Anthropic model) via Cursor. Same-model review is explicitly rejected as insufficient for security validation.

2. **Threat model is external-attack scoped.** Petasos defends against adversarial input aimed at the agent from outside. Internal agent misbehavior (the agent itself acting maliciously) is Hermes's responsibility, not Petasos's. Findings in that category are flagged informational, not blocking.

3. **Every catch is documented, not just exploits.** Blocked attacks are validation evidence. The findings ledger must include both successful and unsuccessful attack attempts to build the confidence case for public release.

4. **OWASP Top 10 for Agentic Applications (2026) is the reference framework.** Findings map to ASI-01 through ASI-10 where applicable.

5. **PyRIT and DeepTeam are candidate automation tools.** Microsoft's PyRIT (v0.11.0, MIT-licensed) provides multi-turn red-teaming orchestration with 70+ prompt converters and crescendo attack strategies. DeepTeam (Apache 2.0) covers 40+ vulnerability types mapped to OWASP. Either or both can supplement manual reviewer-agent passes for the evasion and bypass lens.

---

## Done When

- [ ] All 6 reviewer lenses have completed a full pass over the scoped files
- [ ] Findings ledger contains ≥50 entries (both exploits and blocked attempts)
- [ ] Every critical and high finding has a remediation plan or accepted-risk justification
- [ ] All critical findings are remediated before PET-12 (release)
- [ ] Attack corpus is committed to `tests/adversarial/` for regression
- [ ] Threat model document is committed to `docs/security/threat-model.md`
- [ ] Findings ledger is committed to `docs/security/red-team-findings.md`
- [ ] OWASP mapping table is included in findings ledger
- [ ] No ReDoS vulnerability exists in any regex pattern in `minimal.py`
- [ ] JWT validator rejects `alg: none`, key confusion, and all known JWT attack classes

---

## Out of Scope

- **Hermes agent internals** — the agent's own reasoning, tool selection logic, and system prompt are not under Petasos's purview.
- **ML model quality** — whether LLM Guard or LlamaFirewall detect a given attack is those libraries' concern. Petasos's responsibility is correct wrapping, threshold enforcement, and fail-mode behavior.
- **Network security** — Petasos is an in-process library with no network surface. There is no REST API to pentest (Console is PET-13, separate scope).
- **Performance testing** — covered by PET-11. Red-team may note performance-related findings (e.g., ReDoS) but systematic benchmarking is not in scope.
- **Supply chain / dependency audit** — third-party package vulnerabilities are tracked separately. Red-team focuses on first-party code.

---

## Landscape — existing tools

Before building custom red-team tooling, evaluate these existing frameworks:

| Tool | License | Relevance | Notes |
|------|---------|-----------|-------|
| **PyRIT** (Microsoft) | MIT | High | 70+ prompt converters, crescendo orchestrator, multi-turn attack chains. Python-native. Can target Petasos's pipeline directly via programmatic API. |
| **DeepTeam** (Confident AI) | Apache 2.0 | Medium | 40+ vulnerability scans mapped to OWASP LLM Top 10. More focused on LLM output safety than guardrail bypass, but useful for evasion corpus generation. |
| **Garak** (NVIDIA) | Apache 2.0 | Medium | LLM vulnerability scanner with probes for prompt injection, encoding attacks, and payload generation. Good corpus source. |
| **Promptfoo** | MIT | Low–Medium | Red-team eval framework with OWASP Agentic mapping. More evaluation-focused than offensive, but the assertion library is useful for regression. |

Recommendation: use PyRIT's prompt converters and crescendo orchestrator for the evasion lens (Lens 5), DeepTeam or Garak for bulk corpus generation, and manual reviewer-agent passes for the remaining lenses.

---

*Brief drafted 2026-05-26. Spec source: PET-14 Plane ticket + petasos-work-items.md + codebase at HEAD 44639fe.*
