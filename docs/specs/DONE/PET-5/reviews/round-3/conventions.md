# PET-5 Spec Review — Conventions (Round 3)

**Spec:** `docs/specs/TODO/PET-5.spec.md` (v3)
**Brief:** `docs/briefs/PET-5-presidioscanner-brief.md`
**Reviewer:** spec-reviewer-conventions
**Round:** 3

---

## Closure of round 2 findings

All round 2 findings CLOSED. No P1/P2 items remained.

---

## Findings

### F-1 (P2) — Top-level `petasos/__init__.py` re-export diverges from PET-3 without rationale

PET-3 only re-exports from `petasos/scanners/__init__.py`. PET-5 adds a re-export from `petasos/__init__.py` as well. Either add a rationale for the deviation or align with PET-3.

### F-2 (P2) — `_ensure_loaded()` omits `threading.Lock` (PET-3 uses one)

PET-3's `_ensure_loaded()` is guarded by a lock because `asyncio.to_thread()` can schedule concurrent calls on different threads. PET-5's `_ensure_loaded()` has no lock. The module-level anonymizer cache correctly uses a lock, but the instance-level lazy init does not.

### F-3 (P3) — Spec line 102 claims PET-3 `_ensure_loaded()` "raises" but PET-3 actually catches-and-caches

PET-3's `_ensure_loaded()` catches import errors and stores the error, then re-raises on subsequent calls from the cached error. The spec's characterization as simply "raises" is slightly inaccurate — it catches, caches, and re-raises. Minor but could mislead an implementer.

### F-4 (P3) — No explicit handling of Presidio's built-in Hash salt behavior

Related to correctness F-3. Presidio v2.2.361+ adds a random salt to its `Hash` operator. The spec should note non-determinism of plain hash mode.

### F-5 (P4) — `anonymize()` docstring convention

PET-3 and the repo's `CLAUDE.md` say "default to writing no comments." The standalone `anonymize()` function is a public API export — a one-line docstring is appropriate here (matches `_SEVERITY_MAP` convention discussion in round 1).

---

STATUS: GREEN
