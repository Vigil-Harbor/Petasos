# Reconciliation Report: PET-67

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-67.spec.md
> Merge: PR #28 (fa938d6)
> Plane state: Done (group: completed)

## Summary
The shipped commit `fa938d6` (PR #28) adds `re.IGNORECASE` to the `system-prefix` injection regex and updates the two named tests exactly as the spec prescribes. Implementation matches spec intent with zero drift; the only extra path in the diff is the standard PET-67.test-output.txt audit artifact.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/scanners/minimal.py` | Yes | `re.IGNORECASE` added to `system-prefix`; current L35 confirmed |
| `tests/adversarial/syntactic/test_injection_evasion.py` | Yes | `test_system_prefix_case_variant` flipped to assert-finding over 3 variants |
| `tests/test_minimal_scanner.py` | Yes | New `test_system_prefix_case_insensitive` added |
| `petasos/normalize.py` (leave alone) | No | Correctly untouched |
| `petasos/pipeline.py` (leave alone) | No | Correctly untouched |
| `docs/security/red-team-findings.md` (post-merge, not in PR) | No | Correctly excluded from PR per spec |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-67.test-output.txt` — test/lint/mypy audit trail produced by the ship workflow, not a substantive change (not counted as drift).

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | Fix at the regex, not the normalizer | Confirmed | `petasos/scanners/minimal.py:35` carries `re.MULTILINE \| re.IGNORECASE`; `normalize.py`/`pipeline.py` untouched in diff |
| 2 | Drawbridge divergence is intentional | Confirmed | No Drawbridge files in diff; change is Petasos-local and consistent with the 7 sibling patterns at `minimal.py:28-36` |
| 3 | Adversarial test flips, not deletes | Confirmed | `tests/adversarial/syntactic/test_injection_evasion.py:26-33` — same function, inverted assertion, updated docstring "case variants ... ARE matched after fix" |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `re.IGNORECASE` added to `system-prefix` pattern | Met | `petasos/scanners/minimal.py:35` |
| 2 | Adversarial test asserts finding IS produced for lowercase/mixed-case variants | Met | `test_injection_evasion.py:29-33` loops `system:`, `System:`, `sYsTeM:` and asserts `any(...)` |
| 3 | Unit test `test_system_prefix_case_insensitive` covers lowercase variant | Met | `tests/test_minimal_scanner.py:47-49` |
| 4 | `pytest <both files>` passes | Met | `PET-67.test-output.txt:49` — "38 passed in 0.15s"; lines 22-24 show the 3 PET-67 tests PASSED |
| 5 | `ruff check . && mypy --strict .` clean | Met | `PET-67.test-output.txt:51,53` — "All checks passed!" / "Success: no issues found in 59 source files" |
| 6 | Red-team ledger SYN-03 row updated with remediation commit (post-merge) | Unverifiable | Spec marks this explicitly out-of-PR. `red-team-findings.md:89` SYN-03 status is "refuted" and `plane-remediation-index.md:59` maps SYN-03→PET-67, but no literal commit hash is recorded in the row. Post-merge tracking item, not part of the shipped diff. |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| `test_system_prefix_case_variant` (adversarial, flipped) | Yes | `tests/adversarial/syntactic/test_injection_evasion.py:26` |
| `test_system_prefix` (unit, regression) | Yes | `tests/test_minimal_scanner.py:43` |
| `test_system_prefix_case_insensitive` (unit, new) | Yes | `tests/test_minimal_scanner.py:47` |
| Full injection suite (8 patterns) | Yes | `tests/test_minimal_scanner.py` TestInjectionPatterns + `red-team-findings.md` SYN-* coverage; all PASS per test-output.txt |
| `ruff check . && mypy --strict .` | Yes | Captured in `PET-67.test-output.txt:51,53` |

## Wiki-ready
- None — routine hardening fix (one-flag regex change with test flip; the only judgment call, regex-vs-normalizer, is local and already captured in the spec).

RECONCILED: yes DRIFT: 0
