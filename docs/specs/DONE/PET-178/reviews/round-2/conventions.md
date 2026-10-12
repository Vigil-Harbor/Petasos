# Conventions Review — round 2

## Closure of round 1 findings
All round-1 P0/P1 items CLOSED or DEFERRED as in the author's closure_manifest. Deferred rows D-1–D-5 well-formed. Round-1 P2/P3 conventions findings CLOSED.

## Findings

### F-1: Ceiling-clean adds a third `format_result_notice` site the PET-77 AST pin still counts as 10
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:19, 239–241 | spec § Banner; spec § Files to change (Tests)
**Suggested fix:** Add `tests/test_reference_plugin_block_messages.py` to Files to change and the Test command. Bump `call_sites == 10` to 11 (or whatever the shipped site count is). Append `format_result_notice("ceiling", ...)` to the model-facing catalogue; do not put the ceiling line-1 sentence in `forbidden`.

### F-2: Round-2 spec-level additions with rationale (c)
**Severity:** P3
**Where:** spec § Banner; spec § Decision 11; spec § Decision 13; spec § CHANGELOG residuals
**Suggested fix:** No design change. Optional: one sentence in § Banner that `"ceiling"` is a new `ResultNoticePath` member added so line 1 does not reuse the findings injection sentence.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 1 | P4: 0

STATUS: GREEN
