# Reconciliation Report: PET-66

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-66.spec.md
> Merge: PR #32 (merge 2bc6022; fix commits 5240962 / c212387 / 5210cbd)
> Plane state: Done (group: completed)

## Summary
The shipped fix replaces every inter-word literal space with `\s+` across `_INJECTION_PATTERNS`, `_ROLE_TRIGGERS`, and `_ROLE_GRANTS` in `minimal.py`, exactly as the spec dictates, and adds the 10 named whitespace-evasion tests plus the flipped bypass assertion. All decisions and acceptance criteria are met; the only delta is one extra (spec-anticipated) test-output artifact in the diff.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/scanners/minimal.py` | Yes | All 6 injection patterns + 4 role triggers + 5 role grants now `\s+`; `system-prefix`/`inst-delimiter` untouched (minimal.py:28-54) |
| `tests/adversarial/syntactic/test_injection_evasion.py` | Yes | 10 new tests added (lines 139-232) |
| `tests/adversarial/normalization/test_unicode_bypass.py` | Yes | `test_double_space_evasion_between_trigger_words` assertion flipped + docstring updated (now line 66-71) |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-66.test-output.txt` — 195-line captured pytest run added as PR audit trail. Not named in the spec's "files to change" table, but it is a non-code documentation artifact produced by the ship workflow; no code or behavioral drift.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | Regex fix, not normalizer fix | Confirmed | `petasos/normalize.py` untouched in diff; fix lives entirely in `minimal.py:28-54`. No whitespace collapsing added. |
| D2 | `\s+` not `\s*` | Confirmed | All replaced patterns use `\s+` (e.g. minimal.py:29 `ignore\s+previous\s+instructions`); no `\s*` used between words. |
| D3 | Role patterns included in same pass | Confirmed | `_ROLE_TRIGGERS` (minimal.py:41-46) and `_ROLE_GRANTS` (minimal.py:48-54) both converted to `\s+` in same commit. |
| D4 | `new-instructions` preserves `\s*:` suffix | Confirmed | minimal.py:33 `new\s+instructions\s*:` — inter-word space is `\s+`, colon suffix kept as `\s*:`. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | 6 injection patterns with inter-word spaces use `\s+` | Met | minimal.py:29-34 (ignore-previous, ignore-all, disregard, you-are-now, new-instructions, system-override) |
| 2 | 4 role triggers use `\s+` | Met | minimal.py:42-45 |
| 3 | 5 role grants use `\s+` | Met | minimal.py:49-53 |
| 4 | 10 new whitespace-evasion tests pass | Met | All 10 functions present: test_injection_evasion.py:139,147,155,163,171,179,187,195,203,223 |
| 5 | `test_double_space_evasion_between_trigger_words` assertion flipped | Met | test_unicode_bypass.py:71 now `assert any("ignore-previous" ...)`; docstring updated (line 67) |
| 6 | `test_redos_patterns_bounded` still passes | Met (present) | Test exists at test_injection_evasion.py:106; new `test_redos_with_flexible_whitespace` (line 223) adds ReDoS guard for `\s+` patterns. Captured run in PET-66.test-output.txt shows full suite green. |
| 7 | ruff check / ruff format --check / mypy --strict clean | Unverifiable (read-only) | Not re-run here; PET-66.test-output.txt records the gate as passing at ship time. |
| 8 | No regression in `pytest .` full suite | Unverifiable (read-only) | Not re-run here; captured test-output artifact shows green. Code-level checks all consistent. |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| test_double_space_ignore_previous | Yes | test_injection_evasion.py:139 |
| test_tab_between_trigger_words | Yes | test_injection_evasion.py:147 |
| test_newline_between_trigger_words | Yes | test_injection_evasion.py:155 |
| test_mixed_whitespace_disregard | Yes | test_injection_evasion.py:163 |
| test_mixed_whitespace_system_override | Yes | test_injection_evasion.py:171 |
| test_role_switch_double_space | Yes | test_injection_evasion.py:179 |
| test_role_grant_double_space | Yes | test_injection_evasion.py:187 |
| test_role_trigger_only_double_space | Yes | test_injection_evasion.py:195 |
| test_single_space_still_matches | Yes | test_injection_evasion.py:203 |
| test_redos_with_flexible_whitespace | Yes | test_injection_evasion.py:223 |
| test_double_space_evasion_between_trigger_words (flipped) | Yes | test_unicode_bypass.py:66 |
| test_redos_patterns_bounded (existing, unchanged) | Yes | test_injection_evasion.py:106 |
| test_system_prefix_case_variant (existing, unchanged) | Yes | test_injection_evasion.py:26 |
| test_suppress_all_injection_leaves_only_structural (spec name) | Name mismatch | Spec named this; actual SYN-08 suppression test is `test_suppress_all_injection_still_detects` (test_injection_evasion.py:55). Cosmetic spec-vs-code naming gap; coverage intent satisfied, no behavioral drift. |

## Wiki-ready
- None — routine hardening fix. The `\s+`-over-`\s*` rationale (D2: preserve word-boundary semantics, avoid `"ignoreprevious"` false positive) and D1 (regex fix avoids shifting `Position` offsets vs. normalizer collapsing) are mildly reusable for future syntactic-rule work but are already captured verbatim in the spec.

RECONCILED: yes DRIFT: 1
