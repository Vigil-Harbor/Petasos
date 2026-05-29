# PET-1 Spec Review — Edge Cases (Round 1)

**Spec:** `docs/specs/TODO/PET-1.spec.md`
**Brief:** `docs/briefs/PET-1-brief.md`
**Round:** 1

---

## Findings

### F-1 [P1] RTL_OVERRIDES and INVISIBLE_CHARS frozensets contain invisible characters inline

The code blocks for `RTL_OVERRIDES` and `INVISIBLE_CHARS` embed the actual Unicode characters directly in string literals:

```python
RTL_OVERRIDES = frozenset("‪‫‬‭‮⁦⁧⁨⁩")
INVISIBLE_CHARS = frozenset(
    "\x00"        # null
    "­"      # soft hyphen
    "​"      # zero-width space
    ...
)
```

For `RTL_OVERRIDES`, the entire frozenset is a single string of invisible characters — impossible to review, diff, or verify correctness. For `INVISIBLE_CHARS`, some entries use `\x00` escapes but most embed the literal invisible character with only a comment for identification.

**Recommendation:** Use `\uXXXX` escape sequences for all non-printable characters. Example:

```python
RTL_OVERRIDES = frozenset([
    "‪",  # LRE
    "‫",  # RLE
    "‬",  # PDF
    "‭",  # LRO
    "‮",  # RLO
    "⁦",  # LRI
    "⁧",  # RLI
    "⁨",  # FSI
    "⁩",  # PDI
])
```

**Impact:** Without escapes, a copy-paste or encoding change silently corrupts the character set. An implementer cannot verify correctness by reading the spec.

### F-2 [P1] MinimalScanner.scan() has no exception guard

The brief states "pipeline never throws" and Decision D3 mentions `PipelineResult.error` carries caught exceptions. The `Scanner` protocol's contract is that `scan()` returns a `ScanResult` — but the spec's `MinimalScanner.scan()` pseudocode has no try/except guard.

If normalization, regex compilation, or JSON depth checking raises an unexpected exception, the scanner propagates it to the caller. This breaks the "never throws" invariant at the scanner level. The pipeline can catch it, but: (a) PET-6 doesn't exist yet, and (b) individual scanners should be self-contained.

**Recommendation:** Wrap the scan body in a try/except that catches `Exception`, returns a `ScanResult` with `error` set and empty findings. Add this to the design section.

### F-3 [P1] JSON depth check can cause RecursionError

The spec says:

> Use `json.loads()` with a custom decoder hook that tracks nesting depth. On `json.JSONDecodeError`, skip the check.

A custom `object_pairs_hook` or `object_hook` doesn't track nesting depth — the `json` module doesn't pass depth information to hooks. The actual implementation requires either:
- Recursive descent with a depth counter (risks `RecursionError` on deeply nested input — the very attack this rule defends against)
- Iterative parsing with an explicit stack
- `sys.setrecursionlimit()` guard (fragile)

The spec should prescribe the iterative approach or at least mandate a `RecursionError` catch alongside `JSONDecodeError`.

**Impact:** A malicious payload with 1000+ nesting levels causes the depth checker itself to crash with `RecursionError`, which is not caught by `except json.JSONDecodeError`.

---

## Closure Table

| Finding | Status | Evidence |
|---------|--------|----------|
| F-1 | OPEN | — |
| F-2 | OPEN | — |
| F-3 | OPEN | — |

STATUS: RED P0=0 P1=3
