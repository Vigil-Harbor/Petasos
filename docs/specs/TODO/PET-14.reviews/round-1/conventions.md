# Conventions Review — round 1

## Findings

### F-1: 5 deliverables; mild redundancy between `security-assertions.md` and `red-team-findings.md` — P3
`security-assertions.md` renders the full inventory; `red-team-findings.md` re-seeds one row per assertion. Same ~70 assertions appear twice. Defensible split (read-only inventory vs mutable ledger) but a single-source-of-truth tension: correcting one grounding requires editing two files.
**Fix (optional):** Note in `security-assertions.md` that the ledger is *generated/derived* from it (inventory = canonical source), or collapse the inventory into the ledger's Expected-behavior column. Option (a) preferred; not blocking.

### F-2: No `## Deferred (P2+)` trailer that PET-10/PET-11 use — P4
Sibling specs close with `## Deferred (P2+)`. PET-14 omits it (expected at round 1; Suspected-gap tags serve a similar role). Core section ordering otherwise matches house style exactly.
**Fix:** Add a `## Deferred (P2+)` trailer if later rounds surface non-folded P2+ items.

### F-3: `Test command: N/A` handling — P4 (informational, no violation)
First doc-only spec in the repo. Handled correctly: D3 rationale, Test plan → reviewer checklist, Test command literally `N/A`, ship-spec Phase 3 skip noted. Right convention to establish.

### F-4: `docs/security/` paths honor the brief exactly — P4 (informational)
Brief mandates `docs/security/threat-model.md` and `docs/security/red-team-findings.md`; spec uses both verbatim. (Note: PET-11 placed its checklist at top-level `docs/security-hardening-checklist.md` — minor repo inconsistency; PET-14 correctly follows the brief's `docs/security/` mandate.)

### F-5: Assertion inventory faithfully reflects every documented invariant — P4 (core check, passes)
Verified against CLAUDE.md "Key Design Invariants" + wiki architecture.md:
- "Pipeline never throws" → PIPE-01 asserts + Suspected-gap (except Exception at L315, not BaseException). Correct.
- "Tier 3 cannot be disabled / hardcoded floor" → CFG-04/ESC-01 assert floor + flag TIER3_FLOOR mutable global (config.py:13). Correct nuance, no contradiction.
- "Frozen exports" → CFG-01/TYP-01/TYP-02/PROF-01; PetasosConfig frozen config.py:25; Suspected-gap on shallow freeze / MappingProxyType-view. Consistent with PET-10 Deferred.
- Fail-mode degraded default → config.py:35; PIPE-02 probes partial-failure fail-open. Aligned.
- JWT constraints → LIC-01/02/03 Held (algorithms=["EdDSA"] license.py:58); LIC-07 flags fromtimestamp L70-71 outside try (ends L65). Accurate.
- OSS/premium split → groups route premium/ vs top-level correctly.
Every invariant framed as a falsifiable claim with correct grounding/tagging (D2/D4 + CLAUDE.md grounding rule). No assertion denies or mis-states a guarantee.

### F-6: Wiki alignment — no duplicate/contradicted decision — P4 (informational)
wiki decisions/ has no Petasos security/threat-model entry → no duplication/contradiction. `2026-04-29-tool-namespacing-double-underscore.md` consistent with GUARD-02. PET-10 Deferred #5 (activate() method-vs-module CLAUDE.md divergence) untouched by PET-14. session_id-unauthenticated trust anchor is a new, well-scoped observation.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 1 | P4: 5
Follows house style, honors brief paths, no premature abstraction/backwards-compat shim; assertion inventory correctly mirrors every documented invariant as a falsifiable claim. One P3 single-source-of-truth note.

STATUS: GREEN
