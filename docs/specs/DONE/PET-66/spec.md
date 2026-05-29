# PET-66 — SYN-02: Flexible Whitespace in Injection Regexes

**Ticket:** PET-66 · **Finding:** SYN-02 · **Priority:** High
**Parent:** PET-14 · **Blocks:** PET-12 (release)

---

## Goal

Harden all keyword-based injection, role-trigger, and role-grant regex patterns in `MinimalScanner` to match across arbitrary whitespace between trigger words. Currently, literal single-space characters in patterns allow trivial evasion via double spaces, tabs, or newlines between words. After this change, `\s+` replaces every inter-word literal space, closing the entire class of whitespace-variation evasion while maintaining the existing zero-false-positive property on concatenated words.

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/scanners/minimal.py` | Replace literal spaces with `\s+` in `_INJECTION_PATTERNS`, `_ROLE_TRIGGERS`, and `_ROLE_GRANTS` |
| `tests/adversarial/syntactic/test_injection_evasion.py` | Add 10 whitespace-evasion tests + 1 regression test for single-space matching |
| `tests/adversarial/normalization/test_unicode_bypass.py` | Flip `test_double_space_evasion_between_trigger_words` assertion — bypass is now closed |

### Files left alone

- `petasos/normalize.py` — no whitespace collapsing needed; regex-level fix is strictly better (no position-offset side effects)
- All premium modules — not affected
- All other scanner backends — not affected

## Decisions

### D1: Regex fix, not normalizer fix

Collapsing whitespace in `normalize()` would break `Position(start, end)` offsets for all findings downstream. Every finding's `position` field reports start/end indices into the normalized text; collapsing runs would shift all indices after the first collapse point. The regex-level `\s+` fix achieves identical detection without any side effects on position tracking.

### D2: `\s+` not `\s*`

Zero-width matches (`\s*`) would match concatenated words like `"ignoreprevious"` — a false positive on legitimate text. Requiring at least one whitespace character (`\s+`) preserves the semantic boundary between trigger words. This matches the brief's explicit decision.

### D3: Role patterns included in same pass

`_ROLE_TRIGGERS` and `_ROLE_GRANTS` have the identical literal-space vulnerability. Fixing them in the same commit avoids a second pass through the same code region and ensures no whitespace-evasion gaps remain in the syntactic layer.

### D4: `new-instructions` pattern preserves `\s*:` suffix

The existing `new-instructions` pattern already uses `\s*:` for the colon suffix (matching zero or more spaces before the colon). Only the inter-word space (`new instructions`) changes to `\s+`. The colon suffix is left as-is.

## Design

### 1. Injection patterns (`minimal.py:28–37`)

Replace the 6 patterns that have inter-word literal spaces. The 2 patterns without inter-word spaces (`system-prefix` and `inst-delimiter`) are unchanged.

```python
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ignore-previous", re.compile(r"ignore\s+previous\s+instructions", re.IGNORECASE)),
    ("ignore-all", re.compile(r"ignore\s+all\s+instructions", re.IGNORECASE)),
    ("disregard", re.compile(r"disregard\s+your", re.IGNORECASE)),
    ("you-are-now", re.compile(r"you\s+are\s+now", re.IGNORECASE)),
    ("new-instructions", re.compile(r"new\s+instructions\s*:", re.IGNORECASE)),
    ("system-override", re.compile(r"system\s+override", re.IGNORECASE)),
    ("system-prefix", re.compile(r"^SYSTEM:", re.MULTILINE)),
    ("inst-delimiter", re.compile(r"\[INST\]|</INST>", re.IGNORECASE)),
]
```

### 2. Role triggers (`minimal.py:41–46`)

All 4 patterns get `\s+` between words:

```python
_ROLE_TRIGGERS: list[re.Pattern[str]] = [
    re.compile(r"you\s+are\s+a", re.IGNORECASE),
    re.compile(r"act\s+as", re.IGNORECASE),
    re.compile(r"pretend\s+you\s+are", re.IGNORECASE),
    re.compile(r"roleplay\s+as", re.IGNORECASE),
]
```

### 3. Role grants (`minimal.py:48–54`)

All 5 patterns get `\s+` between words:

```python
_ROLE_GRANTS: list[re.Pattern[str]] = [
    re.compile(r"no\s+restrictions", re.IGNORECASE),
    re.compile(r"no\s+limits", re.IGNORECASE),
    re.compile(r"without\s+filters", re.IGNORECASE),
    re.compile(r"DAN\s+mode", re.IGNORECASE),
    re.compile(r"developer\s+mode", re.IGNORECASE),
]
```

### 4. No changes to `_check_injection`, `_check_role_switch`, or suppression logic

The detection methods iterate over the pattern lists and call `.search()`. Since the patterns themselves are the only thing changing (same tuple structure, same list type), no method logic needs updating. The suppress-rules mechanism references rule IDs derived from pattern slugs, which are unchanged.

## Test plan

All new tests go in `tests/adversarial/syntactic/test_injection_evasion.py`. Existing tests in that file must continue to pass unchanged.

### New tests (10)

| # | Test name | Input | Asserts |
|---|-----------|-------|---------|
| 1 | `test_double_space_ignore_previous` | `"ignore  previous  instructions"` | Finding with rule_id `petasos.syntactic.injection.ignore-previous` |
| 2 | `test_tab_between_trigger_words` | `"ignore\tprevious\tinstructions"` | Finding with rule_id `petasos.syntactic.injection.ignore-previous` |
| 3 | `test_newline_between_trigger_words` | `"ignore\nprevious\ninstructions"` | Finding with rule_id `petasos.syntactic.injection.ignore-previous` |
| 4 | `test_mixed_whitespace_disregard` | `"disregard  your"` | Finding with rule_id `petasos.syntactic.injection.disregard` |
| 5 | `test_mixed_whitespace_system_override` | `"system\t override"` | Finding with rule_id `petasos.syntactic.injection.system-override` |
| 6 | `test_role_switch_double_space` | `"you  are  now"` | Finding with rule_id `petasos.syntactic.injection.you-are-now` |
| 7 | `test_role_grant_double_space` | `"you  are  a helpful assistant with no  restrictions"` | Finding with rule_id `petasos.syntactic.injection.role-switch-capability` (input includes trigger to exercise full role-switch-capability path) |
| 8 | `test_role_trigger_only_double_space` | `"pretend  you  are a helpful assistant"` | Finding with rule_id `petasos.syntactic.injection.role-switch-only` (trigger-only path with whitespace evasion) |
| 9 | `test_single_space_still_matches` | All 8 canonical single-space injection inputs | Each produces its expected finding (regression guard) |
| 10 | `test_redos_with_flexible_whitespace` | `" " * 5000 + "ignore" + " " * 5000 + "previous"` | Pattern completes in <1s; no catastrophic backtracking |

### Existing test requiring update

- `test_double_space_evasion_between_trigger_words` (`tests/adversarial/normalization/test_unicode_bypass.py:37`) — currently asserts the bypass works (`assert not any(...)`). After `\s+` fix, the bypass is closed. Flip assertion to `assert any("ignore-previous" in f.rule_id ...)` and update docstring to note the bypass is now closed by PET-66.

### Existing tests (must pass unchanged)

- `test_redos_patterns_bounded` — validates all injection patterns complete quickly on adversarial input
- `test_suppress_all_injection_leaves_only_structural` — validates suppression still works
- `test_system_prefix_case_variant` — unaffected (system-prefix pattern unchanged)
- All other tests in the full suite

## Test command

```
python -m pytest tests/adversarial/syntactic/test_injection_evasion.py tests/adversarial/normalization/test_unicode_bypass.py tests/test_minimal_scanner.py -v && python -m pytest . && ruff check . && ruff format --check . && mypy --strict .
```

## Done when

- [ ] All 6 injection patterns with inter-word spaces use `\s+` instead of literal space
- [ ] All 4 role triggers use `\s+` instead of literal space
- [ ] All 5 role grants use `\s+` instead of literal space
- [ ] 10 new whitespace-evasion tests pass
- [ ] `test_double_space_evasion_between_trigger_words` assertion flipped (bypass now closed)
- [ ] `test_redos_patterns_bounded` still passes with updated patterns
- [ ] `ruff check .`, `ruff format --check .`, and `mypy --strict .` clean
- [ ] No regression in `python -m pytest .` full suite

## Out of scope

- Whitespace collapsing in `normalize.py` — would break position tracking; unnecessary given regex fix
- Unicode whitespace categories beyond `\s` — Python's `re` module `\s` already covers `\t`, `\n`, `\r`, `\f`, `\v`, `\x85`, `\xa0`, and Unicode Zs category
- Drawbridge backport — uncoupled repo, own ticket prefix (DBR), own remediation cadence
- Adding new injection patterns beyond the existing 8 — separate finding/ticket
- Changes to pattern slugs or rule IDs — these are stable identifiers referenced by profiles and suppress lists
