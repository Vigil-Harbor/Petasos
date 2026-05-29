# Reconciliation Report: PET-44

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-44.spec.md
> Merge: PR #41 (0661a03)
> Plane state: Done (group: completed)

## Summary
The four normalize-hardening layers (NORM-02 re-strip, NORM-04 NFD+Mn strip, NORM-03 44-entry homoglyph table, NORM-05 chr()-form RTL_OVERRIDES) shipped exactly as specified; current `petasos/normalize.py` matches the spec's Design section verbatim and all 21 named tests are present. The only deviations are benign: two test classes were named differently than the spec suggested, and a test-output audit artifact appears in the diff.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/normalize.py` | Yes | Steps 4/5/6 added, table expanded to 44, RTL_OVERRIDES → chr(); matches spec Design 1:1 |
| `tests/test_normalize.py` | Yes | +162 lines; 18 unit tests across 4 new classes |
| `tests/adversarial/normalization/test_unicode_bypass.py` | Yes | NORM-03/04 assertions flipped to "fixed"; defense-in-depth test added |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-44.test-output.txt` (+70) — pytest run capture / ship-spec audit artifact, not code. Non-substantive.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | Re-strip after NFKC is belt-and-suspenders; `nfkc_restrip_applied` appended only when chars stripped | Confirmed | normalize.py:147-154 (re-strip pass; transform appended inside `if restrip_count > 0`) |
| D2 | NFD decompose then strip Mn (lossy by design); original preserved | Confirmed | normalize.py:156-164 (NFD, strip cat==Mn, NFC recompose); `original=original` returned at :174 |
| D3 | Curated 44-entry table, no library dep; fullwidth omitted; µ key is U+03BC not U+00B5 | Confirmed | normalize.py:63-115 (44 entries; `"μ": "u"` at :100, no U+00B5 key); test_normalize.py:285-291 verifies micro-sign path |
| D4 | RTL_OVERRIDES → chr() form + strippable validation test | Confirmed | normalize.py:7-19 (9 chr() entries); test_normalize.py:324-326 (`test_rtl_overrides_all_strippable`) |
| D5 | Combining-mark stripping unconditional (no config toggle) | Confirmed | normalize.py:156-164 runs unconditionally inside `normalize()`; no toggle gates it |
| D6 | 6-step ordering: RTL → strip → NFKC → re-strip → NFD+Mn → homoglyph | Confirmed | normalize.py steps labelled 1-6 at :129/:134/:142/:147/:156/:166 in stated order |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Re-strip pass appends `nfkc_restrip_applied` when active (NORM-02) | Met | normalize.py:148-152 |
| 2 | NFD+Mn strip appends `combining_marks_stripped` when active (NORM-04) | Met | normalize.py:157-162 |
| 3 | `_HOMOGLYPH_TABLE` ≥ 40 mappings incl. Cyrillic к/х/н/т/м + uppercase, Greek τ/η/µ + uppercase | Met | normalize.py:63-115 (44 entries); test_homoglyph_count_at_least_40 (test_normalize.py:293) |
| 4 | `RTL_OVERRIDES` uses chr() and all members `_is_strippable()` | Met | normalize.py:7-19; test_normalize.py:324-326 |
| 5 | "ign"+U+0301+"ore" → "ignore" | Met | test_combining_mark_stripped_after_nfkc (test_normalize.py:216-221) asserts == "ignore previous instructions" |
| 6 | Cyrillic к (U+043A) → "k" | Met | test_homoglyph_cyrillic_ka_mapped (test_normalize.py:236-238) |
| 7 | All 21 listed tests pass | Met | All 18 unit + 3 adversarial functions present (grep below); PET-44.test-output.txt records passing run |
| 8 | Adversarial tests updated to assert fixes | Met | test_unicode_bypass.py:90 (`_now_mapped`), :98 (`_now_stripped`), :108 (defense-in-depth) |
| 9 | `ruff check .` and `mypy --strict .` clean | Unverifiable | Read-only reconcile; not re-run. Commit 2007f9b applied ruff format; no contrary evidence |
| 10 | No regression in full `pytest` suite | Unverifiable | Read-only reconcile; not re-run. test-output artifact present but full-suite run not independently confirmed |

Grep confirming test presence: 18 functions in tests/test_normalize.py:203-347, 3 functions in tests/adversarial/normalization/test_unicode_bypass.py:90/98/108.

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| test_nfkc_restrip_no_op_on_clean_input (#1) | Yes | test_normalize.py:203 |
| test_nfkc_restrip_wiring (#2) | Yes | test_normalize.py:207 |
| test_combining_mark_stripped_after_nfkc (#3) | Yes | test_normalize.py:216 |
| test_combining_mark_precomposed_stripped (#4) | Yes | test_normalize.py:223 |
| test_combining_mark_no_op_ascii (#5) | Yes | test_normalize.py:228 |
| test_homoglyph_cyrillic_ka_mapped (#6) | Yes | test_normalize.py:236 |
| test_homoglyph_cyrillic_kha_mapped (#7) | Yes | test_normalize.py:240 |
| test_homoglyph_cyrillic_en_mapped (#8) | Yes | test_normalize.py:244 |
| test_homoglyph_uppercase_cyrillic (#9) | Yes | test_normalize.py:248 |
| test_homoglyph_greek_tau_mapped (#10) | Yes | test_normalize.py:265 |
| test_homoglyph_greek_uppercase (#11) | Yes | test_normalize.py:269 |
| test_homoglyph_greek_mu (#12) | Yes | test_normalize.py:285 |
| test_homoglyph_count_at_least_40 (#13) | Yes | test_normalize.py:293 |
| test_all_original_17_homoglyphs_preserved (#14) | Yes | test_normalize.py:296 |
| test_rtl_overrides_all_strippable (#15) | Yes | test_normalize.py:324 |
| test_rtl_overrides_count_unchanged (#16) | Yes | test_normalize.py:328 |
| test_pipeline_order_strip_nfkc_restrip_mn_homoglyph (#17) | Yes | test_normalize.py:335 (in class TestPipelineIntegration, not TestEdgeCases) |
| test_normalize_idempotent_with_mn_strip (#18) | Yes | test_normalize.py:346 (in class TestPipelineIntegration) |
| test_cyrillic_homoglyph_k_now_mapped (#19) | Yes | test_unicode_bypass.py:90 |
| test_combining_mark_between_letters_now_stripped (#20) | Yes | test_unicode_bypass.py:98 |
| test_nfkc_restrip_defense_in_depth (#21) | Yes | test_unicode_bypass.py:108 |

Note: spec said tests 6-14 would extend existing `class TestHomoglyph` and tests 17-18 the existing `class TestEdgeCases`; they instead landed in new classes `TestExpandedHomoglyph` and `TestPipelineIntegration`. Organizational only — all functions present, behavior unchanged. Not counted as drift.

## Wiki-ready
- None — routine hardening fix. (D2/D5 lossiness-and-unconditional rationale and D3's curated-table-vs-library trade-off are already captured in the spec/brief and are domain-standard; no novel reusable decision surfaced during reconciliation.)

RECONCILED: yes DRIFT: 1
