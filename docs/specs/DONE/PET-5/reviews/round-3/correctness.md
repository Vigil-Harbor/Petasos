# PET-5 Spec Review — Correctness (Round 3)

**Spec:** `docs/specs/TODO/PET-5.spec.md` (v3)
**Brief:** `docs/briefs/PET-5-presidioscanner-brief.md`
**Reviewer:** spec-reviewer-correctness
**Round:** 3

---

## Closure of round 2 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | `@classmethod` on operator methods | CLOSED | spec lines 204-219: instance methods with `self`, params optional |
| F-2 | Per-finding mask/replace incompatible with per-entity-type API | CLOSED | spec lines 179-197: dual-path anonymization — engine path for redact/hash, manual path for replace/mask |
| F-3 | Anonymize behavior list numbering skip | CLOSED | list renumbered |
| F-4 | Mask mode example typo | CLOSED | spec line 245: "mith" correct |
| F-5 | `_ensure_loaded()` convention claim says "PET-3/PET-4" | CLOSED | spec line 102: "PET-3 convention" with PET-4 divergence noted |
| F-6 | `operate()` signature makes `params` required | CLOSED | spec lines 211, 215: `params: dict[str, Any] | None = None` |
| F-7 | Plane ticket not cached in MCP memory | CLOSED | non-blocking (brief is source of truth) |

---

## Findings

### F-1 (P2) — `entities` default described as `["DEFAULT"]` is misleading

Spec line 92: "defaults to `None`, which maps to `["DEFAULT"]` at analysis time." Presidio's `analyze()` treats `entities=None` as "all entities" internally — `"DEFAULT"` is not a literal string the code passes. The spec should say `None` (all built-in entity types) rather than implying a string literal `"DEFAULT"` is used.

### F-2 (P2) — Top-level `petasos/__init__.py` re-export diverges from PET-3

Spec line 34 re-exports from `petasos/__init__.py`. PET-3 only re-exports from `petasos/scanners/__init__.py`, not the top-level package. If this is intentional, add a rationale. If not, remove the `petasos/__init__.py` change.

### F-3 (P2) — Presidio's built-in `Hash` operator uses a random salt since v2.2.361

When `hash_key is None`, the spec falls back to `Hash(hash_type="sha256")`. Since Presidio v2.2.361, the built-in `Hash` operator adds a random salt by default, making hashes non-deterministic across calls. Document this: plain-hash mode without a key is not correlatable — callers should provide a `hash_key` for deterministic hashing.

### F-4 (P3) — `score_threshold` testing gap remains from round 2

Test plan lacks a specific test verifying that findings below `score_threshold` are filtered out. Add to test plan.

---

STATUS: GREEN
