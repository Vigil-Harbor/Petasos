# Brief 8 · Scanner + Syntactic Hardening

**Plane items:** PET-60 (SCAN-02), PET-64 (SCAN-06), PET-68 (SYN-04), PET-69 (SYN-05), PET-70 (SYN-07)
**Files touched:** `petasos/scanners/minimal.py`, `petasos/scanners/llm_guard.py`, `petasos/scanners/presidio.py`, `tests/adversarial/syntactic/`, `tests/adversarial/scanner/`
**Priority:** medium (SYN-04, SYN-07, SCAN-06); low (SCAN-02, SYN-05)
**Parent:** PET-14 · **Blocks:** PET-12 (release)

---

### Findings

| ID | Severity | Attack | Current behavior | Remediation |
|----|----------|--------|------------------|-------------|
| SCAN-02 | low | ML scanner returns `risk_score=99` | `llm_guard.py` and `presidio.py` store raw confidence from backend; no clamping to [0,1] | Add `confidence = max(0.0, min(1.0, raw_confidence))` clamp in each scanner's finding construction |
| SCAN-06 | medium | Overlap merge divergence across Presidio paths | Three different overlap resolution strategies: `merge_findings()` in pipeline, `_resolve_overlaps()` in Presidio engine path, and manual path — can produce different redaction spans | Unify: all paths call `merge_findings()` for overlap resolution before anonymization; Presidio's internal overlap handling is bypassed |
| SYN-04 | medium | Embed NUL byte (`\x00`) in payload | `_BINARY_PATTERN` is `[\x01-\x08\x0e-\x1f]` — excludes `\x00` and `\x7f` (DEL) | Extend to `[\x00-\x08\x0e-\x1f\x7f]` to include NUL and DEL |
| SYN-05 | low | Deep brackets inside JSON string literals -> false positive | `_check_json_depth` counts all `[{` characters including those inside JSON string values | Use a state-tracking counter that skips characters inside `"..."` strings (handle escaped quotes) |
| SYN-07 | medium | Force `_scan_impl` exception -> empty `ScanResult(error=...)` treated as clean | Scanner error returns `ScanResult(error=..., findings=())` — pipeline counts it as "scanner ran, found nothing" in fail-mode logic | In pipeline `_compute_safe()`, treat `ScanResult(error=...)` from MinimalScanner as a failure signal (same as ML scanner errors, since MinimalScanner is the zero-dep baseline) |

### Approach

1. **SCAN-02 (confidence clamp):** Add `_clamp_confidence(raw: float) -> float` helper to each scanner wrapper. Apply at `ScanFinding` construction. This is defense-in-depth alongside TYP-02's `__post_init__` clamp in Brief 2.

2. **SCAN-06 (overlap unification):** Refactor `PresidioScanner.anonymize()` to accept pre-merged findings from the pipeline rather than computing its own overlap resolution. The pipeline calls `merge_findings()` first, then passes the deduplicated finding list to `anonymize()`. Remove `_resolve_overlaps()` from Presidio or mark it as internal-only.

3. **SYN-04 (binary pattern):** One-line fix: change `_BINARY_PATTERN` from `[\x01-\x08\x0e-\x1f]` to `[\x00-\x08\x0e-\x1f\x7f]`.

4. **SYN-05 (JSON depth false positive):** Rewrite `_check_json_depth()` with a minimal state machine:
   - Track `in_string: bool`
   - On `"`: toggle `in_string` (unless preceded by `\`)
   - Only count `[{` when `not in_string`
   - This is still O(n) and avoids a full JSON parse

5. **SYN-07 (scanner error -> blocking):** In `_compute_safe()`, add MinimalScanner errors to the ML error count (or a separate `syntactic_error` flag). In `degraded` and `closed` modes, a MinimalScanner error -> `safe=False`. In `open` mode, pass through (consistent with existing open-mode semantics). This is justified because MinimalScanner is the zero-dep safety net — if it errors, nothing is scanning.

### Decisions carried forward

- **SYN-05 state machine vs. full JSON parse:** A full `json.loads()` with depth tracking would be more accurate but adds overhead and fails on non-JSON payloads. The state machine handles the common false-positive case (brackets in string literals) without requiring valid JSON. Accepted residual: brackets in non-JSON text with `"..."` quoting patterns will still be skipped; this reduces false positives at the cost of very rare false negatives on deliberately crafted payloads.
- **SYN-07 MinimalScanner error classification:** MinimalScanner errors are *extremely* unlikely (it's pure regex with no external deps). If it errors, something is deeply wrong. Treating it as a blocking failure in `degraded` mode is the conservative choice.
- **SCAN-06 breaking change:** Removing `_resolve_overlaps()` or changing `anonymize()` signature is an internal API change. The public API (`Pipeline.inspect()`) is unchanged. Presidio users who call `anonymize()` directly should use `merge_findings()` first — document in docstring.

### Done when

- [ ] `LlmGuardScanner` finding with raw confidence 99.0 -> `ScanFinding.confidence == 1.0`
- [ ] Presidio anonymization uses pipeline's `merge_findings()` for overlap resolution
- [ ] Payload containing `\x00` triggers `binary-content` finding
- [ ] `_check_json_depth('{"key": "[[["}')` returns depth 1 (not 4)
- [ ] MinimalScanner internal error in `degraded` mode -> `safe=False`
- [ ] >= 15 tests (3 per finding)
- [ ] `mypy --strict` clean
- [ ] Existing scanner and pipeline tests still pass

### Out of scope

- SCAN-03 (cancel during `to_thread`) — confirmed, low, documentation-only remediation
- Full JSON schema validation in syntactic scanner
- Scanner-specific circuit breakers (see PET-50)
