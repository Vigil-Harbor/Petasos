# PET-6 Spec Review — Conventions (Round 1)

## Findings

### F-1 (P2): Wiki needs update for new Pipeline signature
**Severity:** P2
**Section:** Scope
The wiki filemap should be updated after PET-6 ships to reflect `pipeline.py` and `config.py`. Not a spec blocker but should be tracked.

### F-2 (P2): Early exit in closed mode is a silent addition from brief
**Severity:** P2
**Section:** Design §4.2, stage 3
The brief mentions early exit as a possibility ("early-exit data for the pipeline") but PET-6 spec makes it concrete behavior. This is a reasonable design choice but should be called out as a decision (D-something) since it's not explicitly mandated by the brief.

### F-3 (P2): Latency benchmarks dropped from done-when
**Severity:** P2
**Section:** Done when
The brief's done-when includes "Latency: syntactic-only < 5ms, single ML scanner < 100ms, full pipeline < 250ms (CPU)" but the spec defers this to PET-11. The deferral is noted in Out of Scope, which is correct practice. No action needed.

### F-4 (P2): v0.1.0-alpha.1 tag dropped from done-when
**Severity:** P2
**Section:** Done when / Out of scope
The brief says "Tag v0.1.0-alpha.1 — OSS tier is shippable" but the spec defers to PET-12. Noted in Out of Scope. No action needed.

### F-5 (P3): Section numbering uses "4.x" but there's no "1/2/3"
**Severity:** P3
**Section:** Design
The design subsections are numbered 4.1, 4.2, 4.3, 4.4, 4.5, 4.6 but the document uses markdown headers (##, ###) not numbered sections. The "4" prefix is misleading — it implies this is section 4 of a larger numbering scheme that doesn't exist. Consider just using descriptive headers.

### F-6 (P3): `normalize()` call doesn't match current signature
**Severity:** P3
**Section:** Design §4.2, stage 1
The spec says "call `petasos.normalize.normalize(text)`" — the actual signature is `normalize(text: str) -> NormalizedText` which returns a `NormalizedText` object with `.text`, `.has_rtl_override`, `.positions`. The spec should reference the return type.

### F-7 (P3): Test plan lists >=10 tests for finding merge but the function is small
**Severity:** P3
**Section:** Test plan
Ten tests for a single merge function is thorough — this is a positive observation, not a concern.

### F-8 (P3): No explicit mention of `__all__` for new modules
**Severity:** P3
**Section:** Scope
Convention in existing files (e.g., `_types.py`) uses `__all__` for exports. New files should follow suit. Minor.

### F-9 (P3): Config `from_dict` extra keys behavior
**Severity:** P3
**Section:** Design §4.1
The test plan says "from_dict() with extra keys ignores them (forward compatibility)" — good defensive choice, consistent with config-forward-compat patterns.

### F-10 (P4): Spec uses "§" notation consistently
**Severity:** P4
**Section:** Throughout
Consistent cross-reference style. No action needed.

### F-11 (P4): Decision numbering continues from brief (D7, D8 are new)
**Severity:** P4
**Section:** Decisions
Good practice — D1-D6 are carried from the brief, D7-D8 are new. Traceable.

### F-12 (P4): Out of scope section is comprehensive
**Severity:** P4
**Section:** Out of scope
All deferred items are explicitly listed with ticket references. No action needed.

## Summary

| Severity | Count |
|----------|-------|
| P0 | 0 |
| P1 | 0 |
| P2 | 4 |
| P3 | 5 |
| P4 | 3 |

STATUS: GREEN
