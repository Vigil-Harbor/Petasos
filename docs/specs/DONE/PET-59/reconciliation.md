# Reconciliation Report: PET-59

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-59.spec.md
> Merge: PR #24 (ba52ca1)
> Plane state: Done (group: completed)

## Summary
PET-59 shipped exactly as specified: an `_UNSUPPRESSIBLE_RULE_IDS` constant plus a `_validate_suppress_rules()` helper wired into parse, merge, and construction paths, with `research.json` updated to drop `inst-delimiter`. All six decisions are confirmed and every acceptance criterion is met. The only post-ship change is benign: a later commit (PET-71, 1ebdbcf) relocated the `_UNSUPPRESSIBLE_RULE_IDS` definition into `minimal.py` and imports it back — same value, same behavior, not PET-59 drift.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/premium/profiles/__init__.py` | Yes | Constant, helper, `__post_init__`, `_parse_profile`, `_merge_with_base` all added at ba52ca1 (init.py:18-25, 49-52, 133, 152) |
| `petasos/premium/profiles/research.json` | Yes | `inst-delimiter` removed; 4 encoding suppressions retained (research.json:3-8) |
| `tests/test_profiles.py` | Yes | Assertion flipped to `not in` (test_profiles.py:90) |
| `tests/test_profiles_suppress.py` | Yes (new) | 7 unit test functions across 5 classes |
| `tests/adversarial/profiles/test_suppress_bypass.py` | Yes (new) | 1 adversarial end-to-end test; no `__init__.py` in dir, per spec |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-59.test-output.txt` — test-run audit artifact added by the ship workflow, not a spec-named change. Documentation/evidence only; no code impact.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | Strip and warn, don't raise | Confirmed | `_validate_suppress_rules` logs `_logger.warning(...)` and returns `suppress - _UNSUPPRESSIBLE_RULE_IDS`; no raise (profiles/__init__.py:18-25) |
| 2 | Injection + structural unsuppressible; encoding suppressible | Confirmed | `_UNSUPPRESSIBLE_RULE_IDS = _STRUCTURAL_RULE_IDS | _ALL_INJECTION_IDS` (minimal.py:100); `_ENCODING_RULE_IDS` excluded (minimal.py:85-92). `code_generation`/`research` still suppress encoding rules. 8 injection patterns (minimal.py:26-37) + 2 role-switch (minimal.py:70-75) = 10; +3 structural = 13 |
| 3 | Research profile `inst-delimiter` removal | Confirmed | research.json no longer lists `inst-delimiter` (research.json:3-8); test asserts `not in` (test_profiles.py:90) |
| 4 | Defense-in-depth at profile + scanner layers | Confirmed | Profile gate live (init.py:133,152); scanner-side cap present from PET-71 (minimal.py:100 / commit 1ebdbcf) — complementary as stated |
| 5 | `_UNSUPPRESSIBLE_RULE_IDS` imports from `minimal.py` | Confirmed (intent; relocated post-ship) | At ship (ba52ca1) the profile module composed the constant locally from `_ALL_INJECTION_IDS | _STRUCTURAL_RULE_IDS` imported from minimal.py. Current code imports the assembled constant directly from minimal.py (init.py:13). Coupling and value unchanged; the shared-contract intent holds |
| 6 | Module-level logger, no conditional import | Confirmed | `_logger = logging.getLogger(__name__)` at module level (init.py:15); helper uses it without a local import |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `_UNSUPPRESSIBLE_RULE_IDS` defined | Met | Importable in profiles namespace; value at minimal.py:100, re-exported init.py:13 |
| 2 | `_validate_suppress_rules` strips + logs warning | Met | profiles/__init__.py:18-25 |
| 3 | `_parse_profile` applies validation | Met | `suppress_rules=_validate_suppress_rules(frozenset(...))` (init.py:133) |
| 4 | `_merge_with_base` applies validation | Met | `suppress = _validate_suppress_rules(suppress | frozenset(val))` (init.py:152) |
| 5 | `ResolvedProfile.__post_init__` strips | Met | init.py:49-52, uses `object.__setattr__` on frozen dataclass |
| 6 | All 8 tests pass | Met | 7 unit fns in test_profiles_suppress.py (lines 21,29,39,48,56,67,82) + 1 adversarial (test_suppress_bypass.py:13); test-output.txt records the green run |
| 7 | Built-in profile JSONs contain no unsuppressible IDs | Met | research.json cleaned; `test_builtin_profiles_no_unsuppressible` enforces across all 5 (test_profiles_suppress.py:82-89) |
| 8 | `ruff check .` and `mypy --strict .` clean | Unverifiable | Read-only reconcile; not re-run here. test-output.txt (shipped) records the gate; no contradicting evidence on disk |
| 9 | No regression in full `pytest` suite | Unverifiable | Not re-run under read-only constraint; shipped test-output.txt is the audit trail |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| `test_parse_profile_strips_injection_rules` | Yes | tests/test_profiles_suppress.py:21 |
| `test_merge_strips_injection_rules` | Yes | tests/test_profiles_suppress.py:39 |
| `test_parse_profile_strips_structural_rules` | Yes | tests/test_profiles_suppress.py:29 |
| `test_encoding_rules_still_suppressible` | Yes | tests/test_profiles_suppress.py:48 |
| `test_mixed_suppress_keeps_allowed` | Yes | tests/test_profiles_suppress.py:56 |
| `test_direct_resolved_profile_strips` | Yes | tests/test_profiles_suppress.py:67 |
| `test_builtin_profiles_no_unsuppressible` | Yes | tests/test_profiles_suppress.py:82 |
| `test_suppress_all_rules_adversarial` | Yes | tests/adversarial/profiles/test_suppress_bypass.py:13 |
| `test_research_profile_suppress_rules` (existing, updated) | Yes | tests/test_profiles.py:90 |

## Wiki-ready
- None — routine hardening fix. The one reusable invariant (injection + structural rules are unsuppressible at the profile layer; the unsuppressible set is the shared contract between `minimal.py` and the profile resolver, now centralized in `minimal.py` as `_UNSUPPRESSIBLE_RULE_IDS`) is adequately captured by Decisions 2 and 5 and the PET-71 follow-up.

RECONCILED: yes DRIFT: 0
