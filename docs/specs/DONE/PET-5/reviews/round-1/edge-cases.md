# PET-5 Spec Review — Edge Cases (Round 1)

**Spec:** `docs/specs/TODO/PET-5.spec.md`
**Brief:** `docs/briefs/PET-5-presidioscanner-brief.md`
**Reviewer:** spec-reviewer-edge-cases
**Round:** 1

---

## Findings

### F-1 (P2) — Empty text input behavior

The spec doesn't specify what happens when `scan("")` is called. Presidio's `AnalyzerEngine.analyze()` accepts empty strings and returns an empty list. The scanner should return `ScanResult(findings=(), scanner_name="presidio", duration_ms=...)` with no error. Worth documenting explicitly.

### F-2 (P2) — Very large text input (>1MB)

Presidio + spaCy may have memory or performance issues with very large inputs. The spec doesn't define a maximum text size or whether oversized payloads should be rejected (MinimalScanner handles this at the structural level). Since Presidio runs after normalization in the pipeline, the pipeline's payload check runs first, but standalone scanner use has no guard.

### F-3 (P2) — Custom entity list validation

If a caller passes invalid entity names (e.g., `entities=["NOT_A_REAL_ENTITY"]`), Presidio silently ignores them and returns no findings. This is confusing but not dangerous. The spec doesn't mention this edge case.

### F-4 (P3) — Unicode text with mixed scripts

Presidio's English-only NER may produce false positives or misses on text with mixed Unicode scripts (e.g., CJK + Latin). Since the scanner defaults to `language="en"`, this is expected behavior. Not a bug, but worth noting in Out of Scope.

### F-5 (P1) — `score_threshold` not plumbed to analyze() call

The constructor accepts `score_threshold` (default 0.35) and stores it as `self._score_threshold`. But the Design section never shows it being passed to `analyzer.analyze(score_threshold=...)`. Without this, Presidio uses its own default threshold (typically 0.0 or 0.5 depending on version), making the constructor parameter dead code.

The spec must explicitly state that `self._score_threshold` is passed as `score_threshold=self._score_threshold` in the `analyzer.analyze()` call. Same for `language` — it should be passed as `language=self._language`.

### F-6 (P2) — Findings from non-Presidio scanners passed to anonymize()

The `anonymize()` function silently skips findings with `position=None`. But what about findings with `position` set but `rule_id` not starting with `petasos.presidio.`? The entity type recovery (strip prefix + uppercase) would produce garbage entity types. The spec should either (a) filter to Presidio-originated findings only, or (b) accept arbitrary entity types in the anonymizer.

### F-7 (P3) — Hash mode with empty hash_key string

The spec says `hash_key: str | None = None` — `None` triggers plain SHA256. But what about `hash_key=""` (empty string)? An empty HMAC key is cryptographically valid but semantically wrong. The spec should specify behavior: treat empty string as `None` (plain SHA256) or use it as-is.

### F-8 (P1) — Mask formula data leak for short values

The spec says "For short values (<=4 chars), the entire value is masked." But the formula `max(len(matched_text) - visible_chars, 0)` with `visible_chars=4` produces `chars_to_mask=0` for a 4-char value, meaning zero characters are masked — the full value is exposed.

For example, a name "John" (4 chars): `max(4 - 4, 0) = 0` → no masking → `John` is returned as-is.

Fix: for values where `len <= visible_chars`, mask the entire value: `chars_to_mask = len(matched_text)`. Or use `max(len(matched_text) - visible_chars, len(matched_text))` conditional logic.

### F-9 (P3) — Mask mode with multi-byte Unicode characters

If `matched_text` contains multi-byte Unicode characters (e.g., accented names like "Rene"), `len()` counts codepoints, not bytes. Presidio's `Mask` operator also works on codepoints. This is correct behavior, but the spec could note that masking is codepoint-based, not byte-based.

### F-10 (P3) — Anonymize called with mixed positioned/unpositioned findings

If findings are a mix of positioned (Presidio) and unpositioned (LLM Guard), the function skips unpositioned ones. But the sort step sorts by `position.start` — if `position` is `None` for some findings, the sort key accessor will raise `AttributeError`. The spec should clarify that filtering happens before sorting.

### F-11 (P4) — Concurrent scan() calls sharing cached engines

Multiple `asyncio.to_thread()` calls hitting the same `self._analyzer` instance concurrently. Presidio's `AnalyzerEngine` is documented as thread-safe for `analyze()` calls. Not a spec issue — just confirming the assumption holds.

---

STATUS: RED P0=0 P1=2 P2=5 P3=3 P4=1
