# PET-35 — Unicode Fold + Strip Reorder in Tool Name Normalization

**Ticket:** PET-35 · **Finding:** GUARD-02 · **Priority:** Urgent
**Parent:** PET-14 · **Blocks:** PET-12 (release)

---

## Goal

Harden `ToolCallGuard._normalize_tool_name()` with NFKC normalization, homoglyph mapping, and `casefold()`, and reorder operations so `strip()` runs before alias lookup. This closes a defense-in-depth gap where Cyrillic/fullwidth confusables in tool names could bypass alias resolution, and fixes a latent inconsistency where whitespace-padded tool names failed to match aliases.

## Scope

### Files to change

| File | What changes |
|------|-------------|
| `petasos/premium/guard.py` | Rewrite `_normalize_tool_name` (L155–184): new order strip → NFKC → homoglyph → casefold → namespace strip → alias lookup; import `_HOMOGLYPH_TABLE` from `normalize.py`; add `import unicodedata` at module level; preserve GUARD-03 alias→exempt defense |
| `petasos/premium/profiles/__init__.py` | Swap 4 `.lower()` calls to `.casefold()` for consistency with guard normalization (L79, L82, L155, L168) |
| `tests/adversarial/guard/test_tool_smuggling.py` | Update `test_whitespace_stripped_after_alias_lookup` assertion; add 4 new smuggling tests (3 Unicode + 1 invisible-char negative test) |
| `tests/test_guard.py` | Update `test_whitespace_stripped` assertion (strip-before-alias changes result); add 5 new normalization tests in `TestToolNameNormalization` |

### Files to leave alone

| File | Reason |
|------|--------|
| `petasos/normalize.py` | `_HOMOGLYPH_TABLE` consumed as-is; no changes to content normalization |
| `petasos/_types.py` | No type changes |
| `petasos/config.py` | No config changes — this is a code-level fix, not configurable |
| `petasos/premium/profiles/*.json` | Profile JSON definitions unchanged; only `__init__.py` call sites change |
| `petasos/premium/escalation.py` | Upstream of guard; unchanged |

## Decisions

### Decision 1: Reuse `_HOMOGLYPH_TABLE`, don't extract to shared module

The brief offers two options: import `_HOMOGLYPH_TABLE` directly from `normalize.py`, or extract to a shared `petasos/_unicode.py`. Direct import is simpler — both modules are internal, the `_` prefix is a convention not an access barrier, and extracting adds a file without reducing coupling. If the table grows or a third consumer appears, extraction can happen then.

### Decision 2: `casefold()` over `lower()`

`casefold()` is the Unicode-correct case-insensitive comparison method. It handles German ß → ss, Turkish İ → i, and other locale-specific mappings that `lower()` misses. For ASCII-only tool names (the common case), `casefold()` and `lower()` are identical — zero performance cost. The brief carries this forward explicitly.

### Decision 3: Strip before alias, not after

The current code strips whitespace *after* alias lookup (L183), which means `" bash "` fails to match the `"bash"` alias key. This is a latent inconsistency — whitespace-padded tool names from buggy runtimes silently bypass alias resolution. Moving strip to the first step fixes this. Two existing tests must update their assertions to reflect the new behavior.

### Decision 4: `unicodedata` import at module level

The brief shows `import unicodedata` inside the method body. Module-level import is preferred: avoids repeated import overhead on every call, follows the existing import style in `guard.py`, and `unicodedata` is a stdlib module with negligible import cost.

### Decision 5: Preserve GUARD-03 defense

The GUARD-03 alias→exempt defense (current L167–180) must be preserved in the rewritten method. The check runs after alias lookup and prevents profile-introduced aliases from redirecting onto exempt keys. The logic is unchanged; only the input to the alias lookup is now normalized.

### Decision 6: Harmonize profiles `.lower()` → `.casefold()` for consistency

`profiles/__init__.py` uses `.lower()` in 4 call sites: exempt-list normalization (L79, L155) and alias→exempt collision checks (L82, L168). The guard now uses `.casefold()` for tool-name normalization and GUARD-03 checks. Leaving profiles on `.lower()` creates a latent inconsistency: for non-ASCII inputs, `casefold()` and `lower()` diverge (e.g., German ß → ss vs ß). Include the 4-site swap in this spec for consistency. Current profile data is ASCII-only, so the change is behavioral no-op today but prevents future divergence.

### Decision 7: Alias-key casefolding deferred (pre-existing gap)

Profile alias-map keys are stored as-is from JSON (only values are `.strip()`'d). After `casefold()` normalization, a tool name `"mytool"` won't match a profile alias key `"MyTool"`. This is pre-existing — `.lower()` also mismatches uppercase alias keys. PET-35 does not worsen it. Fixing it requires either casefolding keys at parse time or at lookup time, which changes profile semantics and warrants its own review. Deferred to a follow-up ticket.

### Decision 8: Casefold after alias resolution

Alias lookup replaces the casefolded tool name with a raw alias value (from `DEFAULT_TOOL_ALIASES` or profile alias maps). The returned string must be fully normalized, so `_normalize_tool_name` applies `strip().casefold()` to the resolved value before returning. This ensures downstream consumers (exempt-list check at `evaluate()` Step 4, tier derivation) always see a casefolded tool name. The current code has the same gap (`.lower()` runs before alias lookup, not after). Since PET-35 is rewriting this method for normalization correctness, fix it here.

## Design

### 1. Module-level imports (`petasos/premium/guard.py`)

Add two imports at the top of the file, after existing imports:

```python
import unicodedata

from petasos.normalize import _HOMOGLYPH_TABLE
```

The `unicodedata` import goes with the stdlib block (after `re`, before `from dataclasses`). The `_HOMOGLYPH_TABLE` import goes with the petasos imports.

### 2. Rewrite `_normalize_tool_name` (L155–184)

Replace the entire method body. New operation order: strip → NFKC → homoglyph → casefold → namespace strip → alias lookup (with GUARD-03 preserved).

```python
def _normalize_tool_name(self, tool_name: str) -> str:
    name = tool_name.strip()
    name = unicodedata.normalize("NFKC", name)
    name = name.translate(_HOMOGLYPH_TABLE)
    name = name.casefold()
    name = _NAMESPACE_PREFIX_RE.sub("", name)
    if self._profile and self._profile.tool_alias_map:
        combined = {**DEFAULT_TOOL_ALIASES, **self._profile.tool_alias_map}
    else:
        combined = dict(DEFAULT_TOOL_ALIASES)
    pre_alias = name
    resolved = combined.get(name, name)
    # GUARD-03: a PROFILE-INTRODUCED alias must not redirect onto an exempt key.
    # Default aliases (bash->exec) onto an operator-exempted target stay legal (D8).
    if (
        resolved != pre_alias
        and self._profile
        and name in self._profile.tool_alias_map
        and resolved.strip().casefold() in self._profile.tool_exempt_list
    ):
        _logger.warning(
            "profile alias %r -> %r blocked: target is exempt (GUARD-03)",
            pre_alias,
            resolved,
        )
        resolved = pre_alias
    return resolved.strip().casefold()
```

Key changes from current code:
- **strip() moved first** — ensures whitespace doesn't prevent alias lookup
- **NFKC normalization added** — collapses fullwidth chars (ｂ → b) and compatibility forms; also closes a fullwidth-underscore evasion path in namespace prefix stripping (NFKC now runs before the regex, so fullwidth `＿` in `mcp＿＿server＿＿tool` normalizes to ASCII `_` before the regex matches)
- **Homoglyph mapping added** — Cyrillic/Greek confusables → Latin equivalents
- **`casefold()` replaces `lower()`** — Unicode-correct case folding
- **GUARD-03 check uses `casefold()` instead of `lower()`** — consistent with the new pipeline (`resolved.strip().casefold()` instead of `resolved.strip().lower()`)
- **Final `strip()` removed** — input is already stripped at the top
- **`return resolved.strip().casefold()`** — ensures the returned tool name is always fully normalized, even when alias values contain whitespace or mixed case (Decision 8)

### 3. Profiles harmonization (`petasos/premium/profiles/__init__.py`)

Swap 4 `.lower()` calls to `.casefold()` — Decision 6:

- **L79**: `frozenset(s.strip().lower() for s in ...)` → `frozenset(s.strip().casefold() for s in ...)`
- **L82**: `{v.lower() for v in alias_map.values()}` → `{v.casefold() for v in alias_map.values()}`
- **L155**: `frozenset(s.strip().lower() for s in val)` → `frozenset(s.strip().casefold() for s in val)`
- **L168**: `{v.lower() for v in alias.values()}` → `{v.casefold() for v in alias.values()}`

All current profile data is ASCII-only, so this is a behavioral no-op today. No new tests required for this change.

### 4. Existing test updates

**4a. `tests/adversarial/guard/test_tool_smuggling.py` — `test_whitespace_stripped_after_alias_lookup` (L24–33)**

The test name and docstring describe pre-fix behavior. Update:
- Rename to `test_whitespace_stripped_before_alias_resolves`
- Update docstring to reflect that strip-before-alias resolves `" bash "` → `"exec"`
- Change assertion: `assert guard._normalize_tool_name(" bash ") == "exec"`
- Remove the negative assertion (`!= "exec"`)

**4b. `tests/test_guard.py` — `test_whitespace_stripped` (L117–119)**

Currently asserts `_normalize_tool_name("  read_file  ") == "read_file"`. After strip-before-alias: `"  read_file  "` → strip → `"read_file"` → ... → alias lookup → `"read"`. Update assertion to `"read"`.

### 5. New tests

**5a. Adversarial tests (`tests/adversarial/guard/test_tool_smuggling.py`)**

Add 4 new tests after the updated whitespace test:

| # | Test name | Input | Expected | What it verifies |
|---|-----------|-------|----------|-----------------|
| 1 | `test_cyrillic_a_in_bash_normalizes` | `"bаsh"` (U+0430) | `"exec"` | Cyrillic а → Latin a via homoglyph table, then alias |
| 2 | `test_fullwidth_bash_normalizes` | `"ｂａｓｈ"` (U+FF42 etc.) | `"exec"` | NFKC collapses fullwidth → ASCII, then alias |
| 3 | `test_mixed_script_shell_normalizes` | `"ѕhell"` (Cyrillic ѕ U+0455) | `"exec"` | Cyrillic ѕ → Latin s via homoglyph, then alias |
| 4 | `test_invisible_chars_not_stripped` | `"ba​sh"` (ZWS via escape) | not `"exec"` | Negative test: invisible char stripping is out of scope; documents known boundary |

These tests follow the existing pattern: construct a bare `ToolCallGuard` without premium activation (normalization is testable without license).

**5b. Unit tests (`tests/test_guard.py` — inside `TestToolNameNormalization`)**

Add 5 new tests:

| # | Test name | Input | Expected | What it verifies |
|---|-----------|-------|----------|-----------------|
| 5 | `test_casefold_not_just_lower` | `"BASH"` | `"exec"` | `casefold()` handles uppercase (confirms method change) |
| 6 | `test_namespace_prefix_with_cyrillic` | `"mcp__server__bаsh"` (Cyrillic а) | `"exec"` | Homoglyph mapping works on chars after namespace strip |
| 7 | `test_plain_ascii_no_regression` | `"bash"` | `"exec"` | ASCII path unchanged — no regression from Unicode additions |
| 8 | `test_empty_string_normalizes` | `""` | `""` | Empty input passes through without error |
| 9 | `test_whitespace_only_normalizes` | `"   "` | `""` | Whitespace-only → empty after strip-first reorder |

These use the existing `_guard(key=valid_key)` helper and follow `TestToolNameNormalization` patterns.

## Test plan

### New tests (9)

1. **`test_cyrillic_a_in_bash_normalizes`** — Construct guard, call `_normalize_tool_name("bаsh")` where `а` is U+0430. Assert returns `"exec"`.
2. **`test_fullwidth_bash_normalizes`** — Call with `"ｂａｓｈ"` (fullwidth Latin). Assert returns `"exec"`.
3. **`test_mixed_script_shell_normalizes`** — Call with `"ѕhell"` where `ѕ` is U+0455 Cyrillic. Assert returns `"exec"`.
4. **`test_invisible_chars_not_stripped`** — Call with `"ba​sh"` (zero-width space via escape sequence, not literal invisible char). Assert does NOT return `"exec"`. Negative test documenting known scope boundary.
5. **`test_casefold_not_just_lower`** — Call with `"BASH"`. Assert returns `"exec"`.
6. **`test_namespace_prefix_with_cyrillic`** — Call with `"mcp__server__bаsh"` (Cyrillic а). Assert returns `"exec"`.
7. **`test_plain_ascii_no_regression`** — Call with `"bash"`. Assert returns `"exec"`.
8. **`test_empty_string_normalizes`** — Call with `""`. Assert returns `""`. Verifies new pipeline handles empty input without error.
9. **`test_whitespace_only_normalizes`** — Call with `"   "`. Assert returns `""`. Verifies strip-first reorder produces empty for whitespace-only.

### Existing test updates (2)

1. **`test_whitespace_stripped_after_alias_lookup`** (test_tool_smuggling.py:24) — Rename to `test_whitespace_stripped_before_alias_resolves`, update assertion from `"bash"` to `"exec"`.
2. **`test_whitespace_stripped`** (test_guard.py:117) — Update assertion from `"read_file"` to `"read"`.

### Existing test regression

All other tests in `test_guard.py` and `test_tool_smuggling.py` pass without modification:
- `TestToolNameNormalization` tests use ASCII inputs — `casefold()` produces identical results to `lower()` for ASCII
- GUARD-03 tests (`test_profile_alias_maps_exec_to_read_exempt`, `test_alias_onto_exempt_runtime_fallback`, `test_whitespace_alias_onto_exempt_runtime_fallback`) — GUARD-03 logic preserved; `casefold()` produces same results as `lower()` for the ASCII alias values in these tests
- `test_alias_exec_to_read_exempt_blocked` (async e2e) — unchanged, tests evaluate() flow not normalization internals

## Test command

```bash
C:\python310\python.exe -m pytest tests/test_guard.py tests/adversarial/guard/test_tool_smuggling.py -v
```

## Done when

- [ ] `_normalize_tool_name` applies strip → NFKC → homoglyph → casefold before namespace strip and alias lookup — maps to Design §2
- [ ] `_HOMOGLYPH_TABLE` imported from `petasos.normalize` — maps to Design §1
- [ ] `unicodedata` imported at module level — maps to Design §1
- [ ] GUARD-03 alias→exempt defense preserved with `casefold()` — maps to Design §2
- [ ] `profiles/__init__.py` 4 `.lower()` → `.casefold()` swaps — maps to Design §3
- [ ] All 9 new tests pass — maps to Test plan §new
- [ ] 2 existing tests updated to match new behavior — maps to Test plan §updates
- [ ] All existing GUARD-03 tests pass without modification — maps to Test plan §regression
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Deferred (P2+)

Advisory findings from round 1–3 reviews (P0/P1 = 0, spec green at round 3):

- **No test for GUARD-03 casefold-specific path** (edge-cases R3 P2): Existing GUARD-03 tests all use ASCII alias values, so `casefold()` == `lower()`. A test with a non-ASCII alias value (e.g., German eszett `"ß"`) would catch a casefold/lower regression. Implementer should consider adding a 10th test.
- **GUARD-03 silent-skip with adversarial profile alias keys** (edge-cases R3 P3): A non-lowercase profile alias key silently never matches the casefolded input. Safe direction but operator intent lost. Pre-existing; covered by Decision 7 deferral.
- **Combining diacritical marks survive NFKC** (edge-cases R3 P3): NFKC normalizes combining pairs to composed forms (e.g., `a` + combining grave → `à`), but the homoglyph table doesn't strip diacritics. Out of scope per homoglyph table expansion deferral.
- **`dict(DEFAULT_TOOL_ALIASES)` copy on every call** (edge-cases R3 P4): Pre-existing pattern. `MappingProxyType.get()` works directly without copying. Performance nit for latency-sensitive path.
- **CLAUDE.md Target Layout stale** (conventions R3 P4): Shows `profiles.py` but actual layout is `profiles/__init__.py`. Not a spec defect; CLAUDE.md update separate.
- **Test command uses hardcoded Python path** (conventions R2 P4): Pre-existing divergence from CLAUDE.md `pytest` convention. Multiple specs in repo use absolute paths.

## Out of scope

- Full content normalization (invisible char stripping, RTL detection) on tool names — overkill for identifiers
- Drawbridge backport (`normalizeForPolicy` has the same gap; separate ticket if needed)
- User-defined tool name validation at the MCP registration layer (upstream concern)
- Expanding the homoglyph table (tracked in `normalize.py`, shared automatically)
- Extracting `_HOMOGLYPH_TABLE` to a shared `_unicode.py` module (premature until a third consumer exists)
- Profile alias-key casefolding (pre-existing gap — `.lower()` also mismatches uppercase alias keys; changing key normalization alters profile semantics and warrants its own ticket — Decision 7)
- Changes to `AuditEmitter` or audit event shape for normalized tool names
