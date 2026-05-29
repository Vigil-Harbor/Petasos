# Correctness Review — round 1

## Findings

### F-1: ESC-02 grounding citation names the wrong file (stale/nonexistent anchor) — P2
**Where:** spec ESC module table, header "ESC — `premium/escalation.py`".
ESC-02 cites `_validate_tier_thresholds (~L19–20)` under the escalation.py header. The function is defined in `config.py:16-22`. `escalation.py` only imports `TIER3_FLOOR` (L9); its L19-24 is the `EscalationResult` dataclass. The cited file:symbol does not exist in the named module.
**Fix:** Re-cite ESC-02 grounding to `config.py:_validate_tier_thresholds (L16-22)` (consumed by escalation). Behavioral claim is correct; only the pointer is wrong.

### F-2: ALRT-03 grounding line range points at the wrong buffer init — P2
**Where:** ALRT-03. Cites `cross_session_burst` buffer `maxlen` at `~L42–45`. At alerting.py:42-45, L42 inits `self._ring_buffers` dict and L43-45 inits `self._pii_ring_buffer`. The cross_session_burst buffer maxlen is established lazily at `alerting.py:256-258` (`setdefault(buf_key, deque(maxlen=...))`). Behavioral claim correct; anchor imprecise.
**Fix:** Point ALRT-03 grounding at `alerting.py:255-264` (`_check_cross_session_burst` buffer + `recent_sessions` set).

### F-3: NORM-03 confidence note miscounts the homoglyph table size — P2
**Where:** NORM-03 says "16 lowercase only". `_HOMOGLYPH_TABLE` (normalize.py:48-68) has 17 entries (Cyrillic 8 + Greek 7 + dotless ı + IPA ɡ). Greek `κ` (L62) IS mapped to `k`; Cyrillic `к` is NOT — disambiguate.
**Fix:** "17 lowercase-only entries"; clarify Greek κ (mapped) vs Cyrillic к (unmapped). Core gap accurate.

### F-4: Plane ticket not retrievable from memory namespace — P3
`memory_search` (namespace plane, tags [plane_work_item,PET-14]) returned 0 results. Verified against the brief instead, which the spec maps faithfully. No contradiction; informational.

## Verification notes (no defect)
- Grounding HEAD valid: tree at d0af5aa (merge of 44639fe); `git diff --stat 44639fe d0af5aa -- petasos/` empty. All 70 assertions verified against live source.
- Assertion count: **70** (NORM6 SYN8 PIPE7 CFG5 TYP4 SCAN6 LIC9 FREQ5 ESC3 GUARD5 AUD3 ALRT4 PROF5) ≥ 50.
- Hard constraints verified: SYN-01 (no ReDoS — all regexes literal/single-bounded) Held; LIC-01/02/03 (EdDSA-only, alg:none reject, key-confusion reject) Held.
- All 10 brief Done-When items map cleanly (6→Bucket B, 4→Bucket A). Fencing internally consistent with D1.
- Spot-checked CORRECT high-risk anchors: LIC-07 (fromtimestamp L70-71 outside try ending L65), GUARD-05 (only TypeError caught L204; RecursionError/circular ValueError escape), PIPE-02 (degraded blocks only on all_ml_failure L116-118), SCAN-05 (unkeyed hash fallback presidio.py:267-269), CFG-04 (TIER3_FLOOR mutable global config.py:13), AUD-03 (verbose config_snapshot includes hash_key), FREQ-02 (_evict_one evicts terminated first frequency.py:218-226).
- Test plan ↔ deliverables 1:1; Test command: N/A consistent with D3. No internal contradictions.

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 1 | P4: 0
The three P2s are imprecise/incorrect grounding anchors (wrong file, wrong line range, off-by-one count); none invalidate the behavioral claim, but D4 makes grounding load-bearing, so correct before handoff.

STATUS: GREEN
