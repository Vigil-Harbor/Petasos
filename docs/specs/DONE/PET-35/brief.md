# PET-35 — GUARD-02: Unicode Fold Missing in Tool Name Normalization

**Plane:** PET-35 · **Finding:** GUARD-02 · **Priority:** Urgent  
**OWASP:** ASI02 — Tool-use manipulation  
**Parent:** PET-14 · **Blocks:** PET-12 (release)  
**Status:** Refuted (code review confirmed existing defense — brief documents gap and hardening)

---

## Problem

`ToolCallGuard._normalize_tool_name()` at L155–168 of `petasos/premium/guard.py` applies four steps: `lower()` (L157), namespace prefix strip (L159), alias map lookup (L161–165), and `strip()` (L167). The finding claimed that Cyrillic `а` (U+0430) in a tool name like `bаsh` (with Cyrillic а) would bypass the alias map because `lower()` does not perform Unicode normalization — the alias key `"bash"` uses Latin `a` (U+0061), so the lookup misses.

**Status: Refuted.** The attack vector described is real in isolation, but the pipeline's content normalization layer (`petasos/normalize.py`) applies NFKC + homoglyph mapping (L96–101) *before* content reaches detection. However, `_normalize_tool_name` operates on the raw tool name passed to `evaluate()`, which does **not** pass through `normalize()`. The tool name comes directly from the agent runtime, not from scanned content.

The refutation holds because agent runtimes (Hermes Desktop) provide tool names from their own tool registry — these are ASCII identifiers controlled by the tool definition, not user-supplied Unicode strings. A Cyrillic-homoglyph tool name would require a compromised tool registry, which is outside the threat model.

**Residual gap:** The finding exposed a real hardening opportunity. If Petasos is ever integrated with runtimes that accept user-defined tool names (e.g., MCP dynamic tool registration), the lack of Unicode normalization in `_normalize_tool_name` becomes exploitable. The fix is cheap and defense-in-depth.

Additionally, the finding noted that alias strip order matters: `strip()` runs *after* alias lookup (L167), meaning `" bash "` would fail to match alias `"bash"` at L165 because `lower()` preserves whitespace. The existing test `test_whitespace_stripped_after_alias_lookup` at `tests/adversarial/guard/test_tool_smuggling.py:23` confirms this: `_normalize_tool_name(" bash ")` returns `"bash"`, not `"exec"`. This is because `lower()` at L157 produces `" bash "`, which does not match the alias key `"bash"` — the alias lookup falls through, then `strip()` at L167 yields `"bash"`. Whether this is a bug or intentional depends on whether whitespace-padded tool names should resolve aliases. The conservative fix is to strip before alias lookup.

## Prior Art

Drawbridge's `normalizeForPolicy()` at `clawmoat-drawbridge-sanitizer/src/guard/index.ts:29–34` also uses only `toLowerCase()` without Unicode normalization. It shares the same theoretical gap. Neither codebase has been exploited via this vector because both consume tool names from controlled registries.

The pipeline-level normalization in both codebases (Petasos `normalize.py`, Drawbridge `validation/normalize.ts`) applies NFKC + homoglyph mapping to *content*, not to tool names. This is the architectural gap: content normalization and tool-name normalization are separate code paths.

## Remediation

### Approach: NFKC + casefold + strip before alias lookup

### Changes

**1. `petasos/premium/guard.py` — `_normalize_tool_name()` reorder and Unicode fold**

Replace L155–168:

```python
def _normalize_tool_name(self, tool_name: str) -> str:
    import unicodedata
    # 1a. Strip whitespace first (before any lookup)
    name = tool_name.strip()
    # 1b. NFKC normalization (fullwidth, compatibility chars)
    name = unicodedata.normalize("NFKC", name)
    # 1c. Homoglyph mapping (Cyrillic/Greek confusables → Latin)
    name = name.translate(_HOMOGLYPH_TABLE)
    # 1d. Casefold (Unicode-aware lowercase)
    name = name.casefold()
    # 1e. Strip namespace prefix
    name = _NAMESPACE_PREFIX_RE.sub("", name)
    # 1f. Map aliases
    if self._profile and self._profile.tool_alias_map:
        combined = {**DEFAULT_TOOL_ALIASES, **self._profile.tool_alias_map}
    else:
        combined = dict(DEFAULT_TOOL_ALIASES)
    name = combined.get(name, name)
    return name
```

**2. `petasos/premium/guard.py` — import homoglyph table**

Add at the top of the file, after existing imports:

```python
from petasos.normalize import _HOMOGLYPH_TABLE
```

Note: `_HOMOGLYPH_TABLE` is currently a module-private name. If exposing it feels wrong, extract it to a shared `petasos/_unicode.py` module that both `normalize.py` and `guard.py` import from. This is a minor refactor — either approach is acceptable for this fix.

**3. Operation order rationale**

The new order is: strip → NFKC → homoglyph → casefold → namespace strip → alias lookup. This ensures:
- Whitespace does not prevent alias resolution (`" bash "` → `"bash"` → alias hit → `"exec"`)
- Cyrillic `а` in `bаsh` → homoglyph maps to `bash` → alias hit → `"exec"`
- `casefold()` instead of `lower()` handles locale-specific folding (e.g., Turkish dotted-I)
- Namespace strip runs on the already-normalized string

## Tests Required

| Test | File | Asserts |
|------|------|---------|
| `test_cyrillic_a_in_bash_normalizes` | `tests/adversarial/guard/test_tool_smuggling.py` | `_normalize_tool_name("bаsh")` (Cyrillic а) returns `"exec"` |
| `test_fullwidth_bash_normalizes` | `tests/adversarial/guard/test_tool_smuggling.py` | `_normalize_tool_name("ｂａｓｈ")` (fullwidth) returns `"exec"` |
| `test_mixed_script_shell_normalizes` | `tests/adversarial/guard/test_tool_smuggling.py` | `_normalize_tool_name("ѕhell")` (Cyrillic ѕ) returns `"exec"` |
| `test_whitespace_before_alias_now_resolves` | `tests/adversarial/guard/test_tool_smuggling.py` | `_normalize_tool_name(" bash ")` returns `"exec"` (strip moved before alias) |
| `test_casefold_turkish_i` | `tests/unit/premium/test_guard.py` | `_normalize_tool_name("BASH")` returns `"exec"` (casefold, not just lower) |
| `test_namespace_prefix_with_unicode` | `tests/unit/premium/test_guard.py` | `_normalize_tool_name("mcp__server__bаsh")` (Cyrillic а) returns `"exec"` |
| `test_plain_ascii_unchanged` | `tests/unit/premium/test_guard.py` | `_normalize_tool_name("bash")` still returns `"exec"` (no regression) |

### Existing test update

`test_whitespace_stripped_after_alias_lookup` at `tests/adversarial/guard/test_tool_smuggling.py:23` currently asserts `_normalize_tool_name(" bash ")` returns `"bash"` (not `"exec"`). After the fix, strip runs before alias lookup, so `" bash "` → `"bash"` → alias → `"exec"`. Update the assertion: `assert guard._normalize_tool_name(" bash ") == "exec"`.

## Decisions Carried Forward

- **Refuted but hardened.** The original finding is refuted under the current threat model (controlled tool registries). The hardening is applied as defense-in-depth against future integration scenarios.
- **Reuse `_HOMOGLYPH_TABLE` from normalize.py.** Single source of truth for confusable mappings. If the table grows, both content normalization and tool-name normalization benefit.
- **`casefold()` over `lower()`.** `casefold()` is the Unicode-correct way to do case-insensitive comparison. It handles edge cases like German eszett (ß → ss) and Turkish dotted-I that `lower()` misses.
- **Strip before alias, not after.** Whitespace-padded tool names from buggy runtimes should still resolve aliases. The old order (strip last) was a latent inconsistency.
- **No import of full `normalize()` function.** Tool names are short identifiers, not content. Applying the full normalization pipeline (invisible char stripping, RTL detection) is overkill and would add confusing `NormalizedText` wrapper overhead.

## Done When

- [ ] `_normalize_tool_name` applies NFKC + homoglyph + casefold before alias lookup
- [ ] Operation order is: strip → NFKC → homoglyph → casefold → namespace strip → alias
- [ ] `_HOMOGLYPH_TABLE` imported from `normalize.py` (or extracted to shared module)
- [ ] All 7 tests listed above pass
- [ ] Existing whitespace test updated to match new behavior
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of Scope

- Full content normalization (invisible char stripping, RTL detection) on tool names — overkill for identifiers
- Drawbridge backport (`normalizeForPolicy` has the same gap; separate ticket if needed)
- User-defined tool name validation at the MCP registration layer (upstream concern)
- Expanding the homoglyph table (tracked in normalize.py, shared automatically)
