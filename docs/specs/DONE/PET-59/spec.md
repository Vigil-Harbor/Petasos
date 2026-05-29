# PET-59 — PROF-04: Allowlist Suppressible Rules in Profiles

**Ticket:** PET-59 · **Finding:** PROF-04 · **Priority:** High
**OWASP:** ASI07 — System prompt and instruction manipulation
**Parent:** PET-14 · **Blocks:** PET-12 (release)
**Related:** PET-71 (SYN-08, scanner-side enforcement)

---

## Goal

Prevent custom profiles from suppressing injection and structural detection rules via `suppress_rules`. Currently, `_merge_with_base()` performs additive union on `suppress_rules` without filtering, and `_parse_profile()` accepts any rule IDs — allowing an attacker who controls profile configuration to suppress all 10 injection detection rules, passing prompt injection payloads through the syntactic pre-filter undetected. This change adds an `_UNSUPPRESSIBLE_RULE_IDS` constant and a `_validate_suppress_rules()` helper that strips unsuppressible rules at parse time, merge time, and direct construction time.

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/premium/profiles/__init__.py` | Add `_UNSUPPRESSIBLE_RULE_IDS` constant, `_validate_suppress_rules()` helper, wire into `_parse_profile()`, `_merge_with_base()`, and `ResolvedProfile.__post_init__()` |
| `petasos/premium/profiles/research.json` | Remove `petasos.syntactic.injection.inst-delimiter` from `suppress_rules` |
| `tests/test_profiles.py` | Update `test_research_profile_suppress_rules` — remove assertion for `inst-delimiter` |

### New files

| File | Purpose |
|------|---------|
| `tests/test_profiles_suppress.py` | 7 unit tests for the validation logic |
| `tests/adversarial/profiles/test_suppress_bypass.py` | 1 adversarial end-to-end test (directory created without `__init__.py`, matching majority adversarial convention) |

### Files unchanged

- `petasos/scanners/minimal.py` — read-only import target; its `_STRUCTURAL_RULE_IDS` guard is unchanged
- `petasos/config.py` — no config surface needed; the unsuppressible set is hardcoded
- `petasos/pipeline.py` — no pipeline changes

## Decisions

### Decision 1: Strip and warn, don't raise

Per the brief: suppression violations are silently stripped with a `logging.warning()`. Unlike GUARD-03 (which raises `ValueError` at construction for alias-exempt collisions), suppress-rule violations are an optimization hint — the attacker gains nothing from the strip, and raising would break legitimate profiles that happen to include an unsuppressible ID (e.g., copy-paste from documentation or future ID changes).

### Decision 2: Injection + structural are unsuppressible; encoding rules remain suppressible

The 4 encoding rules (`invisible-chars`, `base64-in-text`, `homoglyph-substitution`, `rtl-override`) are legitimately noisy in some contexts (e.g., `code_generation` profile suppresses all 4 encoding rules). The 10 injection rules (`_ALL_INJECTION_IDS`) and 3 structural rules (`_STRUCTURAL_RULE_IDS`) are never legitimately suppressed.

### Decision 3: Research profile `inst-delimiter` removal

The `research.json` profile currently suppresses `petasos.syntactic.injection.inst-delimiter`. Since this is an injection rule, it falls under the unsuppressible set. Rather than let the validation silently strip it at load time (creating a mismatch between declared and effective `suppress_rules`), the JSON file is updated to remove it. The existing test at `tests/test_profiles.py:89` is updated accordingly. This narrows the research profile's detection surface — `inst-delimiter` will now fire for research sessions.

### Decision 4: Defense-in-depth at both profile and scanner layers

`MinimalScanner` already strips `_STRUCTURAL_RULE_IDS` from its `_suppress_rules` at `__init__`. PET-59 adds injection rules to the profile layer's gate. PET-71 (SYN-08) will later add injection rules to the scanner layer. The two are complementary, not redundant — the profile layer catches the suppression before it reaches any scanner.

### Decision 5: `_UNSUPPRESSIBLE_RULE_IDS` imports from `minimal.py`

This creates intentional coupling between the profile module and the minimal scanner's rule taxonomy. The rule IDs are the shared contract. If a new scanner adds injection rules with different ID prefixes, the constant must be updated.

### Decision 6: Module-level logger, no conditional import

The `_validate_suppress_rules()` function uses `logging.getLogger(__name__)` at module level — not a lazy import inside the function body as the brief's pseudocode suggests. Module-level logger follows standard Python conventions and avoids repeated `import logging` overhead. The logger is created once at module import time.

## Design

### 1. `_UNSUPPRESSIBLE_RULE_IDS` constant

At module level in `petasos/premium/profiles/__init__.py`, after existing imports:

```python
import logging

from petasos.scanners.minimal import _ALL_INJECTION_IDS, _STRUCTURAL_RULE_IDS

_logger = logging.getLogger(__name__)

_UNSUPPRESSIBLE_RULE_IDS: frozenset[str] = _ALL_INJECTION_IDS | _STRUCTURAL_RULE_IDS
```

This yields 13 rule IDs: 8 injection pattern rules + 2 role-switch rules + 3 structural rules.

### 2. `_validate_suppress_rules()` helper

```python
def _validate_suppress_rules(suppress: frozenset[str]) -> frozenset[str]:
    blocked = suppress & _UNSUPPRESSIBLE_RULE_IDS
    if blocked:
        _logger.warning(
            "suppress_rules attempted to suppress unsuppressible rules "
            "(stripped): %s",
            sorted(blocked),
        )
    return suppress - _UNSUPPRESSIBLE_RULE_IDS
```

Returns the cleaned set. Callers assign the return value.

### 3. Wire into `_parse_profile()` (L91)

Current:
```python
suppress_rules=frozenset(data.get("suppress_rules", [])),
```

After:
```python
suppress_rules=_validate_suppress_rules(frozenset(data.get("suppress_rules", []))),
```

### 4. Wire into `_merge_with_base()` (L110)

Current:
```python
suppress = suppress | frozenset(val)
```

After:
```python
suppress = _validate_suppress_rules(suppress | frozenset(val))
```

### 5. `ResolvedProfile.__post_init__()` defense-in-depth

Add to the `ResolvedProfile` dataclass:

```python
def __post_init__(self) -> None:
    cleaned = _validate_suppress_rules(self.suppress_rules)
    if cleaned != self.suppress_rules:
        object.__setattr__(self, "suppress_rules", cleaned)
```

Uses `object.__setattr__` because the dataclass is `frozen=True`. Delegates to `_validate_suppress_rules()` so the warning is emitted on this path too — honoring Decision 1's strip-and-warn contract consistently. On the normal `_parse_profile`/`_merge_with_base` paths, the set is already clean, so `__post_init__` is a no-op (no double-warning). This also covers `ProfileResolver.register()` transitively — any `ResolvedProfile` passed to `register()` will have already been validated at construction time.

### 6. `research.json` update

Remove `"petasos.syntactic.injection.inst-delimiter"` from the `suppress_rules` array. The profile retains its 4 encoding rule suppressions.

### 7. Existing test update

In `tests/test_profiles.py`, the `test_research_profile_suppress_rules` test asserts `inst-delimiter` is in the research profile's `suppress_rules`. After the JSON change, this assertion is removed. The test continues to verify the encoding rule suppressions.

## Test plan

### Unit tests — `tests/test_profiles_suppress.py`

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_parse_profile_strips_injection_rules` | `_parse_profile` with all `_ALL_INJECTION_IDS` in `suppress_rules` produces a profile with none of them in `suppress_rules` |
| 2 | `test_merge_strips_injection_rules` | `_merge_with_base` with injection IDs in overrides strips them from result |
| 3 | `test_parse_profile_strips_structural_rules` | `_parse_profile` with `_STRUCTURAL_RULE_IDS` in `suppress_rules` strips them |
| 4 | `test_encoding_rules_still_suppressible` | Encoding rules (e.g., `base64-in-text`) remain in `suppress_rules` after parse and merge |
| 5 | `test_mixed_suppress_keeps_allowed` | A mix of injection + encoding IDs retains only the encoding IDs |
| 6 | `test_direct_resolved_profile_strips` | `ResolvedProfile(suppress_rules=frozenset(_ALL_INJECTION_IDS))` strips them via `__post_init__` |
| 7 | `test_builtin_profiles_no_unsuppressible` | All 5 built-in profiles (post-JSON fix) have zero overlap with `_UNSUPPRESSIBLE_RULE_IDS` |

### Adversarial test — `tests/adversarial/profiles/test_suppress_bypass.py`

| # | Test | Asserts |
|---|------|---------|
| 8 | `test_suppress_all_rules_adversarial` | Activates premium license (`pipe.activate(valid_key)` via `valid_key` fixture). Passes the suppress-all dict as a per-call profile override: `pipe.inspect(text, profile={"suppress_rules": list(RULE_TAXONOMY)}, session_id="s1")` — this exercises `resolve() -> _merge_with_base() -> __post_init__`, the realistic attacker path. Asserts at both layers: (a) the resolved profile's `suppress_rules` contains no unsuppressible IDs, and (b) the pipeline returns injection findings end-to-end |

### Existing test update

| File | Test | Change |
|------|------|--------|
| `tests/test_profiles.py` | `test_research_profile_suppress_rules` | Remove assertion for `inst-delimiter` in `suppress_rules` |

## Test command

```
python -m pytest tests/test_profiles_suppress.py tests/adversarial/profiles/test_suppress_bypass.py tests/test_profiles.py -v && ruff check . && ruff format --check . && mypy --strict .
```

## Done when

- [ ] `_UNSUPPRESSIBLE_RULE_IDS` constant defined in `petasos/premium/profiles/__init__.py`
- [ ] `_validate_suppress_rules` strips unsuppressible rules and logs warning
- [ ] `_parse_profile` applies `_validate_suppress_rules`
- [ ] `_merge_with_base` applies `_validate_suppress_rules`
- [ ] `ResolvedProfile.__post_init__` strips unsuppressible rules
- [ ] All 8 tests listed above pass
- [ ] Built-in profile JSON files verified to contain no unsuppressible rule IDs
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of scope

- Scanner-side injection rule unsuppressibility (PET-71 / SYN-08 — separate brief)
- Profile schema versioning (profiles don't have a version field today)
- Drawbridge backport (uncoupled; own ticket if needed)
- Per-rule suppression severity tiers (e.g., allowing suppression of specific low-confidence injection rules — future work if needed)
- Custom scanner rule ID registration (only `MinimalScanner` rules are in scope today)
- Logging the stripped rule IDs to the audit trail (AuditEmitter is not wired to profile resolution)

## Deferred (P2+)

- **Double-stripping on normal path (P2):** `_validate_suppress_rules` cleans the set in `_parse_profile`/`_merge_with_base`, then `__post_init__` runs again on already-clean set. Intentionally idempotent — the `if cleaned != self.suppress_rules` guard prevents unnecessary `object.__setattr__` and avoids double-warning.
- **Circular import constraint (P2):** The new `from petasos.scanners.minimal import ...` creates a dependency edge. `scanners/minimal.py` must not import from `premium/profiles/` to avoid circular imports. Today safe; noted as a constraint on future evolution.
- **`ResolvedProfile` construction precludes unsuppressible IDs for testing (P2):** `__post_init__` makes it impossible to construct a `ResolvedProfile` with unsuppressible rule IDs for any purpose. Tests needing such objects would require `object.__setattr__` escape hatch. No existing tests are affected.
- **Brief/spec test file name divergence (P3):** Brief specifies `tests/unit/premium/test_profiles.py`; spec renames to `tests/test_profiles_suppress.py` to match flat layout convention and avoid collision with existing `tests/test_profiles.py`.
- **No test for warning log output (P3):** The "warn" half of "strip and warn" is untested. Consider adding a `caplog` assertion to one of the stripping tests (e.g., test #1 or #6) to verify `logging.warning()` fires.
- **`_merge_with_base` validates full union including base (P3):** The validation runs on `suppress | frozenset(val)` (base + overrides), so base-profile poisoning via `register()` is also caught on the merge path. This is correct but coincidental — add a code comment to prevent future refactoring to override-only validation.
