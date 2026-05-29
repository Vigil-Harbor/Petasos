# PET-14 — Red-Team Security Review: Presentable Instruction Set + Grounded Assertions

**Ticket:** PET-14 ("Red-team it") · Plane `df20de1d-b048-4569-9fe9-47a420faeae7` · High priority
**Parent:** PET-11 · **Blocks:** PET-12 (release) · **Blocked by:** PET-10 (landed at `44639fe`)
**Spec author:** Claude (Opus 4.7) · **Grounded against:** `petasos/` at HEAD `44639fe`
**Brief:** `docs/specs/TODO/PET-14.brief.md`

---

## Goal

Produce the **presentable red-team package** — the instruction set and code-grounded assertion inventory that a *different model* (GPT-5.5 via Cursor, per the brief's mandatory cross-model decision) will execute against the Petasos codebase. This spec's deliverable is **documentation only**: a formalized threat model, a 6-lens reviewer runbook, a grounded "assertions that should be true" inventory, and a findings-ledger template. ship-spec authors these artifacts; it does **not** perform the adversarial review itself (that would violate the brief's cross-model requirement) and does **not** remediate findings or populate the ledger with review results (both downstream).

The package is "ready to present" when every assertion cites a real `file:symbol`, the threat model and lenses are complete, and the ledger schema is fixed — so the user can "let other models loose" with it.

---

## Scope

### New files (all authored by ship-spec)

| File | Purpose |
|------|---------|
| `docs/security/README.md` | One-screen index of the security package + how to run the cross-model pass. |
| `docs/security/threat-model.md` | Formalized threat model: 8 external-attack categories, in/out-of-scope, OWASP ASI mapping, trust anchors. |
| `docs/security/red-team-runbook.md` | Methodology: cross-model requirement, the 6 formalized lenses, attack-corpus categories, tooling landscape, ledger schema, OWASP table, execution steps. |
| `docs/security/security-assertions.md` | The code-grounded assertion inventory (rendered from this spec's Design section). Each assertion is a claim the red-team attempts to falsify. |
| `docs/security/red-team-findings.md` | Findings-ledger **template**: schema, OWASP mapping table, and the assertion inventory pre-seeded as ledger rows (status `unverified`) for the cross-model pass to confirm/refute. |

### Files explicitly NOT touched

- **No `petasos/` source change.** This is review *preparation*, not remediation. Any code fix is downstream (a separate ticket after findings land), gated before PET-12.
- **No `tests/adversarial/` corpus code.** Corpus *generation* is part of the cross-model execution (PyRIT/DeepTeam/Garak per the brief); the runbook specifies its required categories and target layout, but ship-spec does not author corpus files.
- No `pyproject.toml`, no CI, no wiki edits (wiki update is post-merge, separate flow).

---

## Decisions

### D1 — Cross-model execution stays downstream (carried from brief Decision 1)
The adversarial review must run on a non-Anthropic model (GPT-5.5/Cursor). ship-spec (Claude) therefore produces the *instructions and assertions only*; it never runs the lenses or writes findings as if it had reviewed. **Why:** same-model review inherits the author model's blind spots; the brief rejects it as insufficient. **How honored:** every Done-When item that is a *review outcome* (lens passes, ≥50 findings, remediation) is fenced to the "Downstream" bucket; ship-spec's bucket is artifact authorship + grounding only.

### D2 — Assertions are falsifiable claims with a confidence tag, NOT pre-baked findings
Our council (the grounding agents in this spec's authorship + the spec-cycle reviewers) produced the assertion set. Each assertion is phrased as "X **should** hold" and carries one of **three** confidence tags:
- **Suspected-gap** — council found evidence the assertion may NOT hold; prime target.
- **Held\*** (Held-conditional) — appears to hold at a specific value/path, but the invariant is brittle, in-process-bypassable, or carries a material caveat (the caveat text follows the tag). A `Held*` is a softer Suspected-gap, not a clean pass.
- **Held** — appears to fully hold with no material caveat.

**Why three, not two:** many council findings are "satisfied at value X but the invariant is reachable/brittle" — a binary Held/Suspected-gap discards that caveat when rendered as a one-word priority hint and sort key, burying real leads (e.g. SYN-07's fail-open-at-scanner) below genuinely-clean rows. Handing the cross-model reviewers Claude's *conclusions* would also re-import the blind spots D1 exists to avoid; framing every row as a claim-to-falsify (confidence = priority hint, not verdict) focuses fresh eyes without dictating outcomes. **How honored:** `security-assertions.md` uses the verb "assert"/"should"; the ledger seeds every assertion with status `unverified`; the render/sort rule is **Suspected-gap first, then Held\*, then Held** within each lens's worklist; any row whose prose contains a material "but …" caveat MUST carry `Held*` (or Suspected-gap), never bare `Held`.

### D3 — Documentation/ops deliverable → `Test command: N/A`
No code or tests ship from this spec, so there is no automated test gate. **Why:** the quality gate for a doc/ops deliverable is human review, not pytest. **How honored:** `## Test command` is `N/A`; `## Test plan` is a reviewer checklist (ship-spec Phase 3 skips the test loop on `N/A`).

### D4 — Grounding is mandatory and load-bearing; the symbol is the anchor, the line number is a hint
Every assertion names a concrete `file:symbol` at HEAD `44639fe`. The **function/symbol name is the load-bearing anchor**; the `~Lnn` line range is an approximate convenience that drifts when `petasos/` changes. **Why:** an ungrounded "should be true" is worthless to a red-teamer and is exactly the stale-claim failure mode CLAUDE.md warns against — and the cross-model pass runs *downstream*, possibly after `petasos/` has moved under the pinned offsets. **How honored:** the correctness reviewer verifies each citation against the actual source (any ungroundable assertion is dropped or corrected, not shipped); and `README.md` + `red-team-findings.md` carry a mandatory **pre-execution staleness check** — verify `git rev-parse HEAD == 44639fe`; if HEAD has moved, run `git diff --stat 44639fe HEAD -- petasos/` and re-ground any cited file that appears before trusting its line offsets.

### D5 — Threat model is external-attack scoped (carried from brief Decision 2)
Petasos guards the perimeter (untrusted input → agent). Internal-agent misbehavior is Hermes's contract. **How honored:** `threat-model.md` marks internal-agent issues as *informational, non-blocking*; the runbook's lenses target the 8 external-attack categories.

### D6 — Every catch documented (carried from brief Decision 3)
Blocked attacks are validation evidence. **How honored:** the ledger schema requires an entry for both successful exploits and blocked attempts; Held assertions become "blocked/validated" rows once confirmed by the cross-model pass.

---

## Design

### Deliverable 1 — `threat-model.md`

Sections:
1. **System position** — Petasos sits between untrusted message content and the agent's tool-execution layer; in-process library, no network surface.
2. **Adversary capability** — controls message content and (where the host exposes it) `session_id`, tool parameters, and config/profile selection.
3. **Eight attack categories** (verbatim from brief §Threat Model): detection bypass, pipeline degradation, frequency/escalation manipulation, ToolCallGuard circumvention, JWT forge/replay, normalization-gap exploitation, config poisoning, audit/alert callback abuse.
4. **OWASP ASI anchors** — ASI01 (Agent Goal Hijack) → syntactic + ML scanners; ASI02 (Tool Misuse) → ToolCallGuard; ASI07 (Guardrail Bypass) → pipeline as a whole. Other ASI categories mapped per-finding during execution.
5. **Out of scope** (carried from brief): Hermes internals, ML model quality, network security, perf benchmarking (PET-11), supply-chain/dependency audit.
6. **Cross-cutting trust anchor** — **`session_id` is unauthenticated**: frequency scoring, guard tier derivation, audit attribution/sequence, and alert dedup all trust the caller-supplied `session_id` with no integrity binding. This single assumption underlies several Suspected-gap assertions and must be stated explicitly.

### Deliverable 2 — `red-team-runbook.md`

Sections:
1. **Cross-model requirement** — GPT-5.5 via Cursor (or any non-Anthropic model); rationale.
2. **The 6 lenses** (formalized from brief §Methodology, each owns a slice of the assertion inventory):

   | # | Lens | Owns assertion groups | Key questions |
   |---|------|----------------------|---------------|
   | 1 | Convention & correctness | TYP, CFG | Types sound? Contracts/invariants enforced? Frozen really frozen? |
   | 2 | Edge cases & fault tolerance | PIPE, FREQ, ESC | Behavior at 0/1/MAX? Simultaneous scanner timeout? `gather` cancelled mid-flight? |
   | 3 | Security vulnerability | LIC, SYN (ReDoS), SCAN | ReDoS? Unsafe deserialization? Timing side-channel in JWT? Weak HMAC? |
   | 4 | Exploitable processes | PIPE, FREQ, AUD, ALRT | Multi-step chains: normalization gap + timeout + fail-open? Cross-session frequency poisoning? |
   | 5 | Evasion & bypass | NORM, SYN, GUARD | Homoglyphs/invisibles the tables miss? Tag chars? Tool-name smuggling? Payload splitting? |
   | 6 | Client/UX watchdog | PIPE (fail-mode), ALRT, GUARD | Does degraded mode communicate? False-positive lockout with no recovery? Error-message state leakage? |

3. **Attack-corpus categories** (verbatim from brief): prompt-injection variants, normalization bypass, scanner-specific evasion, pipeline-state attacks, JWT attacks, config mutation, tool-parameter smuggling. **Target layout:** `tests/adversarial/<category>/` (created downstream during execution).
4. **Tooling landscape** (from brief): PyRIT (MIT, converters + crescendo, Lens 5), DeepTeam (Apache-2.0, OWASP corpus), Garak (Apache-2.0, corpus), Promptfoo (MIT, regression assertions).
5. **Findings-ledger schema** — the 10 fields (Finding ID, Lens, Severity, OWASP mapping, Attack vector, Expected behavior, Actual behavior, Affected file:line, Remediation, Status).
6. **Execution steps** — how to drive the assertion list through GPT-5.5 in Cursor, per-lens, producing ledger rows. Each lens **claims and must close every seeded ledger row whose `Lens` field it owns** (a row owned by multiple lenses is closed by the first that reaches it); a lens pass is not complete until all its owned `unverified` rows reach a terminal status (ties into Deliverable 4's seed-closure invariant). Begin with the pre-execution staleness check (D4).

### Deliverable 3 — `security-assertions.md` — the grounded assertion inventory

The **canonical source** for the assertion set (the ledger in Deliverable 4 is *derived* from it — correct grounding here, regenerate there). Rendered from the tables below (**74 assertions**). Each row: **ID**, **Assertion** (should-be-true), **Grounding** (`file:symbol`), **Confidence** (Suspected-gap / Held\* / Held per D2), **Lens**, **OWASP**. Confidence is a *priority hint for the red-team*, not a verdict; the cross-model pass sets the true status in the ledger. Sort within each lens worklist: Suspected-gap → Held\* → Held.

#### NORM — `normalize.py`
| ID | Assertion (should hold) | Grounding | Confidence | Lens | OWASP |
|----|----|----|----|----|----|
| NORM-01 | `normalize()` removes all zero-width/format chars an attacker can use to split a trigger phrase. | `normalize.py:normalize` strip stage (`INVISIBLE_CHARS`, ~L21–46,90) | Suspected-gap (U+E0000–E007F tag chars, U+00A0 NBSP, U+2800, U+180E, variation selectors NOT in set) | 5 | ASI01 |
| NORM-02 | Re-stripping is unnecessary because NFKC cannot reintroduce a strippable char after the strip stage. | order: strip (L90) → NFKC (L96) | Suspected-gap (no re-strip after NFKC) | 5 | ASI01 |
| NORM-03 | Homoglyph folding maps the confusables an attacker would use to spell a trigger. | `_HOMOGLYPH_TABLE` (~L48–68) | Suspected-gap (17 lowercase-only entries; Greek κ mapped but Cyrillic к/х/т/etc. and ALL uppercase Cyrillic/Greek unmapped) | 5 | ASI01 |
| NORM-04 | Combining marks inserted between trigger letters do not defeat downstream regex. | (no combining-mark logic exists) | Suspected-gap (no NFD-strip pass) | 5 | ASI01 |
| NORM-05 | RTL/bidi override controls are removed, not just detected. | `RTL_OVERRIDES` ∩ `INVISIBLE_CHARS` (L82–90) | Held\* (removal works only via strip-set overlap; detection/strip sets must stay manually in sync — brittle coupling) | 5 | ASI01 |
| NORM-06 | `normalize()` is idempotent on its output string. | whole function | Held | 1 | — |

#### SYN — `scanners/minimal.py`
| ID | Assertion | Grounding | Confidence | Lens | OWASP |
|----|----|----|----|----|----|
| SYN-01 | No regex in the scanner is vulnerable to catastrophic backtracking (ReDoS). *(Hard constraint — brief Done-When.)* | `_INJECTION_PATTERNS`, `_BASE64_PATTERN`, `_BINARY_PATTERN`, role regexes | **Held** (council found every pattern literal / single-bounded-quantifier; no nested unbounded quantifiers) | 3 | ASI07 |
| SYN-02 | Injection rules match across benign whitespace variation between trigger words. | `_check_injection` literal-space patterns (~L28–37,238–259) | Suspected-gap (single-literal-space; double-space/tab/NBSP evade) | 5 | ASI01 |
| SYN-03 | The `^SYSTEM:` rule catches case/space variants. | `system-prefix` regex (MULTILINE, not IGNORECASE) | Suspected-gap (`system:`/`SYSTEM :` evade) | 5 | ASI01 |
| SYN-04 | Binary/control-char detection flags smuggled control bytes. | `_BINARY_PATTERN` `[\x01-\x08\x0e-\x1f]` (~L58,192) | Suspected-gap (NUL `\x00`, DEL `\x7f`, C1 `\x80–\x9f` not flagged) | 3 | ASI07 |
| SYN-05 | JSON-depth check measures real structural nesting. | `_check_json_depth` (~L221–236) | Suspected-gap (naive bracket count over raw string incl. string literals) | 2 | ASI07 |
| SYN-06 | Oversized-payload and structural rules cannot be suppressed away. | `__init__` subtracts `_STRUCTURAL_RULE_IDS` (~L112) | Held | 1 | ASI07 |
| SYN-07 | Scanner never raises; on internal error returns `ScanResult(error=...)` with no findings. | `scan` try/except (~L133–148) | Held\* (never-raises holds, but it is fail-open-at-scanner — a crash yields empty findings, not a block; `assert` at L317 is stripped under `python -O`) | 2 | ASI07 |
| SYN-08 | A crafted input cannot reduce detection to only the 3 structural CRITICALs. | suppression model (~L242,281,295,321,337,356,372) | Suspected-gap (all injection+encoding rules suppressible) | 6 | ASI07 |

#### PIPE — `pipeline.py`
| ID | Assertion | Grounding | Confidence | Lens | OWASP |
|----|----|----|----|----|----|
| PIPE-01 | `inspect()` never raises for any input. | `inspect` try/except `Exception` (~L289–320) | Suspected-gap (`asyncio.CancelledError`/`BaseException` escape; `gather` at ~L371 has no `return_exceptions`) | 2 | ASI07 |
| PIPE-02 | In `degraded` mode, content cannot pass when ML defense is effectively down. | `_compute_safe` (~L90–124) | Suspected-gap (partial ML failure → fail-open; knock out all-but-one scanner via timeout/OOM) | 4 | ASI07 |
| PIPE-03 | A per-scanner timeout converts a stalled scanner into a counted error (not a hang). | `_scan_one` `asyncio.wait_for(timeout=30.0)` (~L137) | Held\* (timeout works, but 30s ≫ the 250ms full-pipeline budget — a single stalled scanner is a 30s latency-amplification / DoS lever) | 2 | ASI07 |
| PIPE-04 | Finding merge/dedup never drops a higher-severity finding in favor of a lower-severity one. | `merge_findings` (~L44–87) | Suspected-gap (confidence dominates severity; high-conf benign overlap deletes low-conf CRITICAL) | 4 | ASI07 |
| PIPE-05 | Per-toggle normalization config is honored. | normalization guard (~L335–345) | Suspected-gap (all-or-nothing: one toggle off disables all four; `normalize()` called with no args) | 5 | ASI01 |
| PIPE-06 | Premium hooks and callbacks cannot let an exception escape the pipeline. | per-hook try/except (~L404–460) | Suspected-gap (`BaseException`; synchronous slow callback blocks loop) | 4 | ASI07 |
| PIPE-07 | A per-request `inspect(profile=...)` dict cannot neutralize a CRITICAL finding for an unlicensed caller. | profile filter/override stages (~L381–401,484–486) | Suspected-gap (licensed caller can self-neutralize via `severity_overrides`/`confidence_floor`) | 4 | ASI07 |
| PIPE-08 | `activate(key)` unlocks premium ONLY on a `VALID` license; `INVALID`/`EXPIRED` clears claims so no premium feature is enabled, and expiry is re-checked on every gate call. | `Pipeline.activate` (~L196–200) + `_check_premium` (~L217–233) | Held\* (logic correct: claims kept only if `VALID`; `_check_premium` re-checks `None`→INVALID and expiry→EXPIRED — but the env-var path `PETASOS_LICENSE_KEY` at ~L188–190 auto-activates at construction, an injection surface if env is attacker-influenced) | 3 | ASI07 |
| PIPE-09 | `deactivate()` fully clears license state + claims; premium is immediately gated off with no residual. | `Pipeline.deactivate` (~L202–204) | Held | 3 | ASI07 |
| PIPE-10 | Live license enable/disable cannot interleave with an in-flight scan to leave premium half-wired. | `activate`/`deactivate` (~L196–204) mutate `_license_state`/`_license_claims` non-atomically; `_check_premium` (~L217–233) | Suspected-gap (no lock; a threaded torn read fails closed but can mis-flip a `VALID` license to `INVALID`; single-loop asyncio has no preemption point between the two writes, so the race needs real threads) | 4 | ASI07 |

#### CFG — `config.py`
| ID | Assertion | Grounding | Confidence | Lens | OWASP |
|----|----|----|----|----|----|
| CFG-01 | `PetasosConfig` cannot be mutated after construction. | `@dataclass(frozen=True)` (L25) | Suspected-gap (shallow freeze; `object.__setattr__` bypass used internally → reachable by any holder) | 1 | ASI07 |
| CFG-02 | Every config field is validated; invalid values raise `ValueError`. | `__post_init__` (~L83–259) | Suspected-gap (boolean toggles never `isinstance(bool)`-checked; `anonymize="no"` enables; empty `hash_key` accepted) | 1 | ASI07 |
| CFG-03 | `from_dict` (the untrusted-config surface) cannot disable normalization or flip safety toggles silently. | `from_dict` (~L272–278) + CFG-02 | Suspected-gap (`normalize_nfkc: 0` passes; no size cap on `frequency_weights`) | 4 | ASI07 |
| CFG-04 | `tier3_threshold` cannot be set below `TIER3_FLOOR=30.0`. *(Invariant.)* | `config.py:_validate_tier_thresholds` (L16–22), `TIER3_FLOOR` (L13) | Held\* (enforced for config values, but `TIER3_FLOOR` is a plain mutable module global — reassigning `config.TIER3_FLOOR` in-process defeats the floor for future configs) | 1 | ASI07 |
| CFG-05 | The Pipeline stores an independent validated copy of config. | `Pipeline.__init__` `config.copy()` (~L161) | Held\* (the copy is genuinely independent of the caller's object, but it remains shallow-frozen per CFG-01 — `object.__setattr__` on the stored copy still mutates pipeline config) | 1 | ASI07 |

#### TYP — `_types.py`
| ID | Assertion | Grounding | Confidence | Lens | OWASP |
|----|----|----|----|----|----|
| TYP-01 | All result/finding dataclasses are `frozen=True`. | `Position`/`ScanFinding`/`ScanResult`/`AuditEvent`/`Alert`/`PipelineResult` | Held | 1 | — |
| TYP-02 | Map-typed fields (`payload`,`context`,`premium_features`) are runtime-immutable, not just annotated. | `_types.py` annotations vs construction sites | Suspected-gap (no coercion in `_types`; immutability depends on each producer wrapping in `MappingProxyType`) | 1 | ASI07 |
| TYP-03 | `ScanFinding.from_dict` rejects malformed positions/confidence. | `from_dict` (~L54–67) | Suspected-gap (no `start<=end`/range/clamp validation; inverted/negative positions flow to anonymize) | 1 | ASI07 |
| TYP-04 | `isinstance(x, Scanner)` guarantees a conforming async `scan`→`ScanResult`. | `Scanner` Protocol `@runtime_checkable` (~L95–106) | Suspected-gap (runtime_checkable checks presence only; bad return type crashes merge) | 1 | ASI07 |

#### SCAN — `scanners/{llm_guard,llama_firewall,presidio}.py`
| ID | Assertion | Grounding | Confidence | Lens | OWASP |
|----|----|----|----|----|----|
| SCAN-01 | A missing/failed ML dependency disables only that scanner; `scan()` returns `ScanResult(error=...)`, never raises. | lazy-load + try/except in all three wrappers | Held (presidio `_ensure_loaded` re-raises; its `scan` catches and stringifies) | 3 | ASI07 |
| SCAN-02 | Reported confidence is clamped to [0,1]. | `llama_firewall` clamps (~L124); `llm_guard`/`presidio` store raw | Suspected-gap (llm_guard `risk_score` and presidio `r.score` unclamped) | 1 | ASI07 |
| SCAN-03 | Sync ML inference never blocks the event loop. | `asyncio.to_thread(...)` in all three | Held\* (offload works, but a `CancelledError` (see PIPE-01) orphans the `to_thread` worker thread — it keeps running on the default executor) | 2 | — |
| SCAN-04 | A scanner configured with all components disabled does not silently count as a healthy "clean" ML scan. | `llama_firewall.scan` empty-components path (~L161–167) | Suspected-gap (returns no-error/no-finding → masks `all_ml_failure`, amplifies PIPE-02) | 4 | ASI07 |
| SCAN-05 | PII anonymization uses a keyed, non-reversible transform. | `_HmacSha256Operator` (~L61–78); fallback `hash` (~L263–269) | Suspected-gap (empty `hash_key` → effectively unkeyed; direct `anonymize(mode="hash",hash_key=None)` → unkeyed SHA256; low-entropy PII dictionary-reversible) | 3 | ASI01 |
| SCAN-06 | All anonymization modes redact the same PII spans (consistent overlap handling). | `_resolve_overlaps` vs engine path vs `merge_findings` | Suspected-gap (three divergent overlap strategies; mask-mode length mismatch on raw-vs-normalized `matched_text`) | 4 | ASI01 |
| SCAN-07 | The extras import guard distinguishes "extra not installed" from "intended scanner failed to load", never silently dropping a scanner the operator expects. | `scanners/__init__.py` ImportError guards (L7–32) | Suspected-gap (guard swallows on `_exc.name` match only; an installed-but-broken extra raising `ImportError(name=<extra>)` is swallowed → scanner silently absent → feeds the PIPE-02/SCAN-04 fail-open chain with no signal) | 4 | ASI07 |

#### LIC — `premium/license.py` (highest-trust module)
| ID | Assertion | Grounding | Confidence | Lens | OWASP |
|----|----|----|----|----|----|
| LIC-01 | Only `EdDSA` is accepted; `RS256`/`HS256`/`ES256` rejected. *(Hard constraint.)* | `validate` `algorithms=["EdDSA"]` (~L54–61) | **Held** | 3 | ASI07 |
| LIC-02 | `alg: none` is rejected. *(Hard constraint.)* | allowlist + key-present (~L57–58) | **Held** (double-protected) | 3 | ASI07 |
| LIC-03 | Asymmetric→symmetric key confusion (public key as HMAC secret) is impossible. *(Hard constraint.)* | single-alg allowlist (~L57) | **Held** | 3 | ASI07 |
| LIC-04 | Missing/corrupt bundled public key fails secure (denies all licenses). | `__init__` → `self._key=None` on error; `validate` guard (~L36–48) | Held\* (fails secure correctly, but the key is trusted as whatever PEM ships in `premium/_keys/` with no in-code checksum/pin — a local package-dir write substitutes the attacker's key) | 3 | ASI07 |
| LIC-05 | Token cleaning cannot enable a bypass (only deletes chars). | `_INVISIBLE_RE.sub` (~L12–14,50) | Held (interior non-base64url char breaks decode → INVALID; strip set incomplete but benign) | 3 | ASI07 |
| LIC-06 | `exp` and `iat` are required; expiry returns `EXPIRED` with no claims. | `options={"require":["exp","iat"]}` (~L59), EXPIRED branch (~L62–63) | Held | 2 | ASI07 |
| LIC-07 | `validate()` never raises on any token. | broad `except Exception` (~L64–65) | Suspected-gap (`datetime.fromtimestamp(payload["exp"/"iat"])` at ~L70–71 is OUTSIDE the try; pathological signed `exp` raises) | 2 | ASI07 |
| LIC-08 | Forged claims (`tier`/`features`) require the private key. | claims built post-`decode` (~L67–73) | Held\* (claims come only from a signature-verified payload, but there is no allowlist on the `tier` string — verify downstream consumers treat an unknown tier as least-privilege) | 3 | ASI07 |
| LIC-09 | Clock-skew leeway cannot be widened to neutralize `exp`. | `__init__` `clock_skew_seconds` (~L34–35) | Suspected-gap (no bound/negative-guard; direct construction with huge leeway neuters expiry; not reachable via module helper) | 3 | ASI07 |

#### FREQ — `premium/frequency.py`
| ID | Assertion | Grounding | Confidence | Lens | OWASP |
|----|----|----|----|----|----|
| FREQ-01 | Exponential half-life decay is mathematically correct and overflow-safe. | `update` Step 6 (~L139–144) | Held | 2 | — |
| FREQ-02 | "Terminated stays terminated." *(Invariant.)* | `update` Step 4 (~L125–132), `terminate_session` | Suspected-gap (durable only while SessionState survives; TTL idle-out, LRU eviction — which evicts terminated FIRST — and `reset()` all clear it) | 4 | ASI07 |
| FREQ-03 | A legitimate user's accumulated score cannot be laundered/reset by an attacker. | LRU `_evict_one` (~L211–228) | Suspected-gap (unauthenticated `session_id`; slow session churn evicts victims; spoofed id can inflate a victim to tier3 — "frame the victim") | 4 | ASI07 |
| FREQ-04 | New-session creation is rate-limited under memory pressure. | `update` Step 2 (~L100–117) | Suspected-gap (conjunctive: no throttle below `max_sessions`; `RATE_LIMITED_RESULT`≡`DISABLED_RESULT` → tripping limiter yields benign "none" verdict) | 4 | ASI07 |
| FREQ-05 | Per-update TTL/eviction scan does not become a self-DoS. | Step 1 (~L90–97) O(n) per call | Held\* (bounded by `max_sessions`, but it is an O(n) full-dict scan on every `update` — a latency cost on the hot path at high session counts) | 6 | — |

#### ESC — `premium/escalation.py`
| ID | Assertion | Grounding | Confidence | Lens | OWASP |
|----|----|----|----|----|----|
| ESC-01 | Tier 3 escalation cannot be disabled. *(Invariant.)* | `evaluate_tier` (escalation.py ~L26–33) + `TIER3_FLOOR` (config.py L13) | Held\* (the floor guards the tier3 *value*, but the whole frequency/escalation subsystem is off by default — `frequency_enabled`/`escalation_enabled=False` — so the invariant protects against lowering, not against a feature-off flip) | 2 | ASI07 |
| ESC-02 | Thresholds are strictly ascending (`tier1<tier2<tier3`). | `config.py:_validate_tier_thresholds` (L16–22; consumed by escalation) | Held | 1 | — |
| ESC-03 | The two tier-derivation sites (`evaluate_tier` and `guard._derive_tier`) agree at every boundary. | escalation `>=` vs `guard.py:_derive_tier` (~L176–185) | Held\* (agree today — both inclusive `>=` — but the comparison logic is duplicated, not shared; a future edit could drift them. Assert parity in the corpus) | 1 | ASI07 |

#### GUARD — `premium/guard.py`
| ID | Assertion | Grounding | Confidence | Lens | OWASP |
|----|----|----|----|----|----|
| GUARD-01 | A tier3/terminated session is blocked before any exempt/param path. | `evaluate` Step 3 (~L103–111) | Held\* (ordering is correct — the tier3 block precedes exempt/param — but it inherits FREQ-02: an evicted termination reports tier "none" and the block is bypassed) | 4 | ASI02 |
| GUARD-02 | Tool-name normalization canonicalizes case/whitespace/namespace/alias so policy keys can't be dodged. | `_normalize_tool_name` (~L155–168) | Suspected-gap (whitespace stripped LAST → `" bash "`→`"bash"` not alias `"exec"`; no Unicode/homoglyph fold → `"Bаsh"` dodges; namespace regex strips only `mcp__ns__`/`hermes__`) | 5 | ASI02 |
| GUARD-03 | Tool aliases cannot redirect a dangerous tool onto a safe/exempt identity. | `combined` alias map (~L162); profile aliases override defaults | Suspected-gap (profile `{"exec":"read"}` lands dangerous tool on exempt-keyed `"read"`; only non-empty value validated) | 2 | ASI02 |
| GUARD-04 | Exempt tools are a deliberate, minimal bypass — exemption never skips needed inspection silently. | `evaluate` Step 4 (~L113–121) | Suspected-gap (exempt = total bypass incl. param scan) | 6 | ASI02 |
| GUARD-05 | Param scanning cannot be crashed or DoS'd by nested/huge/circular params. | `_scan_params` (~L187–224) | Suspected-gap (`json.dumps` `RecursionError`/circular `ValueError` uncaught → escapes `evaluate`; no depth/size cap) | 2 | ASI02 |

#### AUD — `premium/audit.py`
| ID | Assertion | Grounding | Confidence | Lens | OWASP |
|----|----|----|----|----|----|
| AUD-01 | Audit sequence numbers form a durable, monotonic, tamper-evident chain. | `emit` (~L42,55), `_prune_stale` (~L106–111) | Suspected-gap (per-session counter resets to 0 after TTL prune / reused id; no chaining hash; in-memory only) | 4 | ASI07 |
| AUD-02 | A failing `on_audit` callback cannot break the pipeline. | `emit` re-raises `RuntimeError` (~L58–62) | Suspected-gap (re-raise propagates; pipeline catches but a throwing sink becomes fail-mode trigger) | 4 | ASI07 |
| AUD-03 | Audit payloads never leak secrets or raw PII content. | `_build_payload` (~L66–104) | Suspected-gap (verbose `config_snapshot` serializes `hash_key`; finding match-text is NOT included — that part Held) | 3 | ASI01 |

#### ALRT — `premium/alerting.py`
| ID | Assertion | Grounding | Confidence | Lens | OWASP |
|----|----|----|----|----|----|
| ALRT-01 | No alert path allows unbounded `on_alert` fan-out. | `evaluate` critical branch (~L93–123) | Suspected-gap (critical alerts skip cooldown + both caps; attacker churns session_ids each crossing tier3 once → unbounded critical fan-out) | 4 | ASI07 |
| ALRT-02 | An attacker cannot starve/suppress legitimate alerts. | per-`rule_id` caps vs `(rule_id,session_id)` cooldown (~L98–116) | Suspected-gap (caps keyed by rule_id only; throwaway sessions exhaust global per-rule minute cap) | 6 | ASI07 |
| ALRT-03 | Ring-buffer overflow cannot blind a cross-session burst detector. | `_check_cross_session_burst` buffer + `recent_sessions` (~L255–264) | Suspected-gap (flood >capacity evicts distinct-session entries → under-counts) | 4 | ASI07 |
| ALRT-04 | A failing `on_alert` callback cannot break the pipeline. | `evaluate` re-raise (~L125–129) | Suspected-gap (same as AUD-02; first critical under flood raises) | 4 | ASI07 |

#### PROF — `premium/profiles/__init__.py`
| ID | Assertion | Grounding | Confidence | Lens | OWASP |
|----|----|----|----|----|----|
| PROF-01 | Built-in profiles are immutable and cannot be mutated by a custom profile. | `_load_builtins` fresh parse (~L173–179); `_merge_with_base` copies (~L156–165) | Held (merge copies base collections) | 1 | ASI07 |
| PROF-02 | A custom profile's "immutable" maps are not mutable via a retained source-dict reference. | `_parse_profile` `MappingProxyType(data.get(...))` (~L81,86) | Suspected-gap (proxy is a view over caller's dict; merge path is safe, parse path is not) | 1 | ASI07 |
| PROF-03 | `register()` cannot poison the `"general"` merge base used by all custom profiles. | `register` (~L194–195) | Suspected-gap (no guard against `register("general", attacker_profile)`; scoped per-resolver instance) | 4 | ASI07 |
| PROF-04 | A custom profile cannot suppress structural/critical detections wholesale. | `suppress_rules` union merge (~L94–99) | Suspected-gap (additive, no allowlist on suppressible rule_ids) — note structural IDs still protected at SYN-06 | 4 | ASI07 |
| PROF-05 | Profile `TierThresholds` inherit the Tier-3 floor + ascending-order invariant. | `TierThresholds.__post_init__` (~L18–19) | Held | 1 | ASI07 |

### Deliverable 4 — `red-team-findings.md` (ledger template, derived from Deliverable 3)

- Header: purpose, cross-model attribution, HEAD pin (`44639fe`), and the **pre-execution staleness check** (D4): verify `git rev-parse HEAD == 44639fe`; if HEAD moved, `git diff --stat 44639fe HEAD -- petasos/` and re-ground any cited file before trusting line offsets.
- **OWASP mapping table**: ASI01 (goal hijack) / ASI02 (tool misuse) / ASI07 (guardrail bypass) → which assertion groups + lenses target them.
- **Ledger table** with the 10 schema fields, **pre-seeded** from `security-assertions.md` (one row per assertion, status `unverified`), sorted within each lens by Suspected-gap → Held\* → Held. The cross-model pass fills Actual-behavior / Status / Remediation.
- **`Held*` closure semantics:** a `Held*` row asserts two things at once (the happy-path holds AND a brittleness caveat exists), so for closure the reviewer treats it **as a Suspected-gap** — the caveat is the claim to falsify. It resolves to `confirmed` only when the happy-path holds AND the caveat is non-exploitable; if the caveat is exploitable it resolves to `refuted` (or spawns a child finding row), never `blocked-validated`. This prevents a confirmed-happy-path closure from silently burying the live lead the `Held*` was created to surface.
- **Seed-closure invariant (exit gate):** every pre-seeded `unverified` row MUST reach a terminal status — `confirmed`, `refuted`, `blocked-validated`, or `accepted-risk` — before Bucket B is declared complete. "≥50 *verified* entries" is necessary but not sufficient; no seed row may remain `unverified` at Bucket B close (the pass also adds new finding rows beyond the seed).
- **Evidence bar (anti-rubber-stamp):** closure of a seed row is not a checkbox — the status must be evidence-justified. Any seed row closed `refuted` or `accepted-risk` MUST carry a non-empty **Actual-behavior** field; `accepted-risk` additionally requires an explicit justification. Every `Suspected-gap`/`Held*` seed MUST record the **attack attempted** (per D6 — every catch documented). If a seed's resolving evidence lives in a newly-added finding row, the seed MUST reference that row's Finding ID. This blocks the laundering path where substance migrates to unlinked new rows while seeds are rubber-stamped.
- A "Validation evidence" note: confirmed-Held / refuted-Suspected-gap assertions become blocked-attempt rows (brief Decision 3 / D6).

### Deliverable 5 — `README.md`

One screen: what each file is, the cross-model requirement, the **pre-execution staleness check** (D4 — verify HEAD `44639fe` or re-ground), and the run order (read threat-model → runbook → drive assertions per lens, claiming owned ledger rows → fill ledger to seed-closure).

---

## Test plan

`Test command: N/A` (doc/ops deliverable, D3). The quality gate is this reviewer checklist:

- [ ] **Grounding:** every assertion in `security-assertions.md` cites a `file:symbol` that exists at HEAD `44639fe` (spot-check ≥1 per module; correctness reviewer verifies all).
- [ ] **Hard-constraint coverage:** the two brief Done-When hard constraints are present as assertions — ReDoS (SYN-01) and JWT attack-class rejection (LIC-01/02/03) — each with current grounding.
- [ ] **Threat model completeness:** all 8 attack categories, in/out-of-scope fences, ASI01/02/07 anchors, and the `session_id`-unauthenticated trust note are present.
- [ ] **Lens completeness:** all 6 lenses formalized, each mapped to ≥1 assertion group; the activate/deactivate seam (PIPE-08/09/10) and the extras-import guard (SCAN-07) are covered.
- [ ] **Ledger schema:** all 10 fields present; OWASP table present; 74 seeded rows (≥50, satisfying the brief's seed target); ledger derived from `security-assertions.md`; seed-closure exit invariant + pre-execution staleness check present.
- [ ] **Scope fence:** no file under `petasos/` changed; no `tests/adversarial/` code authored; no `pyproject.toml`/CI/wiki edits.
- [ ] **Confidence discipline (D2):** three tags used (Suspected-gap / Held\* / Held); no bare `Held` row carries a material "but …" caveat; sort order Suspected-gap → Held\* → Held; ledger seeds every row `unverified`; no row states a Claude verdict as final.
- [ ] **Grounding-anchor discipline (D4):** `file:symbol` is the load-bearing citation; line numbers approximate; the downstream staleness check is documented in README + ledger.
- [ ] **Markdown lint:** files pass the repo's markdown conventions (tables render, headings nest).

## Test command

N/A

---

## Done when

### Bucket A — Ship-spec deliverable (this spec; produced + reviewable now)
- [ ] `docs/security/threat-model.md` committed, covering 8 categories + OWASP anchors + trust-anchor note. *(maps brief: threat-model doc committed)*
- [ ] `docs/security/red-team-runbook.md` committed, formalizing all 6 lenses + corpus categories + tooling + ledger schema + execution steps. *(maps brief: 6 lenses defined; tooling evaluated)*
- [ ] `docs/security/security-assertions.md` committed (canonical inventory, 74 assertions); every assertion grounded to a real `file:symbol`; confidence tagged Suspected-gap / Held\* / Held per D2. *(the "assertions that should be true")*
- [ ] `docs/security/red-team-findings.md` ledger template committed, derived from the inventory: 10-field schema + OWASP table + 74 seeded `unverified` rows (≥50) + the seed-closure exit invariant + the pre-execution staleness check. *(maps brief: ledger committed; OWASP table included; ≥50-entry seed)*
- [ ] SYN-01 (no ReDoS) and LIC-01/02/03 (JWT alg/none/key-confusion) present as grounded assertions. *(maps brief hard constraints — as assertions, not as completed remediation)*
- [ ] `docs/security/README.md` index committed.

### Bucket B — Downstream (cross-model execution; NOT satisfied by ship-spec — tracked on PET-14 execution / follow-on, gated before PET-12)
- [ ] All 6 lenses complete a full GPT-5.5/Cursor pass over the scoped files, each closing every seeded ledger row it owns.
- [ ] **Seed closure:** every pre-seeded `unverified` assertion row reaches a terminal status (`confirmed`/`refuted`/`blocked-validated`/`accepted-risk`) — no row left `unverified`.
- [ ] Ledger reaches ≥50 *verified* entries (status set by the cross-model pass), exploits and blocked attempts both recorded.
- [ ] Every critical/high finding has a remediation plan or accepted-risk justification.
- [ ] All critical findings remediated before PET-12.
- [ ] Attack corpus generated and committed to `tests/adversarial/` for regression.
- [ ] SYN-01 / LIC-01/02/03 confirmed (or refuted + remediated) by the cross-model pass.

---

## Deferred (P2+)

- **Plane ticket not in MCP memory cache** (correctness R1 P3) — `memory_search` returned 0 for PET-14; spec was grounded against `PET-14.brief.md` (the local source of truth) with no contradiction. No spec action; if the cross-model executor needs the Plane ticket text, link it at execution time.
- **PET-11's `docs/security-hardening-checklist.md` sits at top-level `docs/`, not `docs/security/`** (conventions R1 P4) — a minor repo inconsistency. PET-14 correctly follows the brief's `docs/security/` mandate; a future cleanup could relocate the PET-11 artifact. Out of scope here.

## Out of scope

- **The cross-model adversarial review itself** — execution is downstream (D1); ship-spec produces the instruction set only.
- **Any `petasos/` source remediation** — fixes for confirmed findings are a separate post-review ticket.
- **`tests/adversarial/` corpus authorship** — generated during execution (PyRIT/DeepTeam/Garak), not by ship-spec.
- **Hermes agent internals**, **ML model detection quality**, **network security** (no network surface; Console = PET-13), **performance benchmarking** (PET-11), **supply-chain/dependency audit** — all carried from brief §Out of Scope.
