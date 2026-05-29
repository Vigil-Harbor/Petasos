# Reconciliation Report: PET-8

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-8.spec.md
> Merge: PR #7 (squash d927f4b)
> Plane state: Done (group: completed)

## Summary
PET-8 (Profiles + ToolCallGuard premium modules) shipped via PR #7 / squash `d927f4b`, and the shipped diff matches the spec's design and acceptance criteria closely: all 5 JSON profiles, `ProfileResolver`, `ToolCallGuard`'s 8-step flow, the pipeline profile hook + confidence-floor/severity-override stages, and 69 profile+guard tests are all present. Three minor drift items: the spec-listed CLAUDE.md edit was dropped, an out-of-scope `tests/test_escalation.py` match-pattern line was changed, and the `customer_service` profile raises injection severity to `critical` rather than the `HIGH` named loosely in the spec's profile table.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/premium/profiles/__init__.py` | Yes | `ResolvedProfile`, `TierThresholds`, `ProfileResolver` (+195 lines) |
| `petasos/premium/profiles/general.json` | Yes | Identity profile, all defaults |
| `petasos/premium/profiles/customer_service.json` | Yes | PII extras present; severity overrides → `critical` (see Decisions/AC notes) |
| `petasos/premium/profiles/code_generation.json` | Yes | 4 encoding rules suppressed, confidence_floor 0.6 |
| `petasos/premium/profiles/research.json` | Yes | 5 suppress rules, floor 0.7, tiers 25/45/70 |
| `petasos/premium/profiles/admin.json` | Yes | tiers 10/20/35, 5 PII entities |
| `petasos/premium/guard.py` | Yes | `GuardResult`, `ToolCallGuard` (+224 lines) |
| `tests/test_profiles.py` | Yes | 31 tests (+259 lines) |
| `tests/test_guard.py` | Yes | 38 tests (+441 lines) |
| `petasos/pipeline.py` | Yes | profile param in `__init__`/`inspect`, `_premium_profile_hook`, `config` property, `is_premium_active`, stages 5b/5c (+100 lines) |
| `petasos/scanners/minimal.py` | Yes | `with_suppress_rules()` factory (+7 lines) |
| `petasos/config.py` | Yes | `TIER3_FLOOR` promoted to public Final, `_validate_tier_thresholds` helper (+29 lines) |
| `petasos/premium/escalation.py` | Yes | imports `TIER3_FLOOR` from `petasos.config` (1 line) |
| `petasos/premium/__init__.py` | Yes | re-exports all 5 new symbols (+11 lines) |
| `petasos/__init__.py` | Yes | exposes new premium symbols (+7 lines) |
| `CLAUDE.md` | **No** | **Dropped** — spec listed under "Files to modify" (Target Layout → `profiles/` package); not in diff |

Unexpected files in diff (not in spec):
- `tests/test_escalation.py` — one-line `pytest.raises(match=...)` change (`tier3_threshold` → `tier3 must be`), needed because the error string moved into the shared `_validate_tier_thresholds`. Spec's Test Plan explicitly said "Existing frequency/escalation tests remain untouched." Counts as Unexpected.
- `docs/specs/TODO/PET-8.test-output.txt` — committed test-output artifact (CLAUDE.md/ship-spec convention; benign, not a code file).

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | `TierThresholds` is a frozen dataclass validated via shared `_validate_tier_thresholds`; `TIER3_FLOOR` canonical in config.py | Confirmed | `config.py:13` `TIER3_FLOOR: Final[float] = 30.0`; `config.py:31` helper; `profiles/__init__.py:34` `TierThresholds.__post_init__` calls it |
| 2 | `escalation.py` imports `TIER3_FLOOR` from config (premium→config direction) | Confirmed | `escalation.py:11` `from petasos.config import TIER3_FLOOR as TIER3_FLOOR` (diff replaced its own `TIER3_FLOOR: float = 30.0`) |
| 3 | Profiles are a package (`profiles/__init__.py` + sibling JSON), loaded via `importlib.resources.files(...).read_text(utf-8)` | Confirmed | `profiles/__init__.py:236-241` `importlib.resources.files(...).joinpath(f"{name}.json").read_text(encoding="utf-8")` |
| 4 | Profile names use underscores (snake_case), not hyphens | Confirmed | JSON filenames `customer_service.json`, `code_generation.json`; `_BUILTIN_NAMES` at `profiles/__init__.py:75-83` |
| 5 | `GuardResult.tier` is `str` not `int` | Confirmed | `guard.py:48` `tier: str` (as shipped, d927f4b) |
| 6 | ToolCallGuard receives `config: PetasosConfig` directly, does not reach into `pipeline._config` | Confirmed | shipped `guard.py` `__init__(... config: PetasosConfig ...)`; `self._config = config` |
| 7 | Profile `tier_thresholds` bridge into guard tier derivation (inline compare, not `evaluate_tier`) | Confirmed | shipped `guard.py` `_derive_tier`: `if self._profile and self._profile.tier_thresholds:` inline `>=` comparisons |
| 8 | ToolCallGuard is standalone, not a pipeline stage | Confirmed | guard is its own class; not added to pipeline stage sequence (only used via `pipeline.inspect` for param scan) |
| 9 | Copy-on-read for per-call profile override (stored scanner/config never mutated) | Confirmed | `pipeline.py:559-570` `_premium_profile_hook` returns `self._minimal_scanner.with_suppress_rules(...)` (new instance); `minimal.py:115` factory returns new `MinimalScanner` |
| 10 | Tier 3 cannot be overridden (hardcoded block) | Confirmed | shipped `guard.py` Step 3 returns `allowed=False` for `tier3` before exempt/profile logic |
| 11 | ToolCallGuard fails open when premium inactive | Confirmed | shipped `guard.py` Step 0 returns `_PREMIUM_INACTIVE` (`allowed=True`) when `not is_premium_active("tool_guard")` |
| 12 | Confidence floor / severity overrides positioned post-merge (Stage 5b/5c), before `_compute_safe` | Confirmed | `pipeline.py:444-448` (5b floor filter) and `452-462` (5c severity override via `replace(f, severity=...)`), both before frequency/safe stages |
| 13 | `_premium_profile_hook` double-gate (premium + non-empty suppress_rules) | Confirmed | `pipeline.py:559-570`: returns stored scanner if `profile is None`, not premium, or no `suppress_rules` |
| 14 | `is_premium_active()` public delegates to `_check_premium()` | Confirmed | `pipeline.py:254` returns `self._check_premium(feature_name)`. Diff also added `_FEATURE_GATES` so `tool_guard_enabled=False` truly disables (CodeRabbit-driven addition beyond spec text; consistent with brief). |
| 15 | `_build_premium_features` uses `_default_profile is not None` + `tool_guard_enabled` | Confirmed (as shipped) | d927f4b diff sets `"profiles": "unlocked" if active and self._default_profile is not None else "locked"` and tool_guard via `tool_guard_enabled`. (Note: current on-disk pipeline.py:306 now reads `"available"`/`"licensed"` — a *later* PET-10 change, not PET-8.) |
| 16 | Namespace stripping regex applied once, no recursion | Confirmed (with note) | Spec used `mcp__[a-zA-Z0-9_]+__`; shipped `guard.py:_NAMESPACE_PREFIX_RE = ^(?:mcp__[a-zA-Z0-9_]+?__|hermes__)` (non-greedy). Behavior matches spec's documented example `mcp__mcp__tool` → `mcp__tool`; refinement, not drift. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | ProfileResolver loads all 5 built-in profiles from bundled JSON and freezes them | Met | `profiles/__init__.py:235-241` loads `_BUILTIN_NAMES`; `ResolvedProfile`/`TierThresholds` are `@dataclass(frozen=True)`; test `test_all_builtins_load` PASSED |
| 2 | Each profile demonstrably adjusts scanner thresholds (tested with MinimalScanner) | Met | `_premium_profile_hook` → `with_suppress_rules`; test `test_code_gen_suppresses_encoding_not_injection` PASSED |
| 3 | Custom profile via dict overrides built-in; unspecified fields inherit from `general` | Met | `_merge_with_base` (`profiles/__init__.py:143-227`); test `test_dict_merge_inherits_from_general` PASSED |
| 4 | `ToolCallGuard.evaluate()` blocks at Tier 2 (unless allowlisted) and Tier 3 (unconditional) | Met | shipped guard Steps 3 & 6; tests `test_tier3_blocks_unconditionally`, `test_tier2_blocks_non_exempt`, `test_tier2_allows_exempt_tool` PASSED |
| 5 | `ToolCallGuard.evaluate()` warns at Tier 1 (allowed=True, findings populated) | Met | shipped guard Step 7; test `test_tier1_allows_with_warning` PASSED |
| 6 | Parameter content scanning routes through `Pipeline.inspect(direction="outbound")` and produces findings | Met | shipped `guard._scan_params` calls `pipeline.inspect(..., direction="outbound", ...)`; test `test_malicious_param_detected`, `test_guard_uses_pipeline_for_param_scan` PASSED |
| 7 | Tool name normalization: case folding, namespace stripping (`mcp__`/`hermes__`), alias mapping, whitespace | Met | shipped `_normalize_tool_name`; tests `test_case_folding`, `test_mcp_namespace_stripping`, `test_hermes_namespace_stripping`, `test_alias_mapping_bash`, `test_whitespace_stripped` PASSED |
| 8 | `Pipeline.inspect()` accepts optional `profile` override without mutating stored config | Met | `pipeline.py:343` profile param; resolved into local `active_profile`; test `test_per_call_override_doesnt_mutate` PASSED |
| 9 | `Pipeline.__init__()` resolves string profile names via ProfileResolver | Met | `pipeline.py:194,228,283-289` `_resolve_profile`; test `test_init_with_profile_string` PASSED |
| 10 | `GuardResult` frozen dataclass with allowed/reason/findings/tier/param_scan_unsafe | Met | `guard.py:43-49` `@dataclass(frozen=True)` with all 5 fields; test `TestGuardResult::test_frozen` PASSED |
| 11 | ≥50 tests across profiles + guard modules | Met | 31 (test_profiles.py) + 38 (test_guard.py) = 69 in the d927f4b diff; full suite 153 passed |
| 12 | All premium code gated behind `self._premium_active` (PET-7 scaffold) | Met | guard Step 0 + `_check_premium`/`_FEATURE_GATES` (`pipeline.py`); stages 5b/5c gated on `_check_premium("profiles")` |

Note on AC profile-table value: the spec's profile table (line 143) describes `customer_service` severity_overrides as "injection rules → HIGH (raise from MEDIUM)", while the shipped JSON raises them to `critical`. AC #1/#2 (profiles load + adjust) are Met; the discrepancy is a Decision-level value drift, recorded below, not an unmet AC (the criteria do not pin the exact severity value).

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| test_profiles.py — all_builtins_load / general_identity / resolve_unknown_keyerror | Yes | tests/test_profiles.py:51,58,69 |
| test_profiles.py — dict_merge_inherits / suppress_rules_union / severity_overrides_merge | Yes | tests/test_profiles.py:188,195,204 |
| test_profiles.py — tier_thresholds_override / partial_raises / none_override | Yes | tests/test_profiles.py:209,215,220 |
| test_profiles.py — register_custom_profile / to_dict_roundtrip | Yes | tests/test_profiles.py:149,118 |
| test_guard.py — tier3/tier2/tier1 blocking + exempt | Yes | tests/test_guard.py:220,233,258 |
| test_guard.py — normalization (case/mcp/hermes/alias/whitespace/no_double_strip/empty) | Yes | tests/test_guard.py:88,93,97,105,117,101,168 |
| test_guard.py — param scanning (empty/none/non-string/malicious) | Yes | tests/test_guard.py:277,283,288,293 |
| test_guard.py — GuardResult frozen / to_dict | Yes | tests/test_guard.py:381,392,407 |
| test_pipeline.py — TestPipelineProfile (init string / invalid / override dict+string / config prop / is_premium_active) | Yes | tests/test_pipeline.py (TestPipelineProfile::* — 6 tests PASSED in output) |
| test_premium_integration.py — TestProfilePipelineIntegration + TestGuardPipelineIntegration | Yes | tests/test_premium_integration.py (12 PASSED in output) |
| test_escalation.py::test_tier3_below_floor_raises (match updated) | Yes | tests/test_escalation.py:64 (out-of-scope edit; PASSED) |

## Wiki-ready
- **TIER3_FLOOR single-source-of-truth in config.py** — constraining: `escalation.py` and `premium/profiles.TierThresholds` both import/validate against `petasos.config.TIER3_FLOOR`, preserving the premium→config dependency direction (never config→premium). Reusable rule for any future tier consumer.
- **ToolCallGuard receives `config` directly, not via `pipeline._config`** — reusable encapsulation pattern (mirrors `FrequencyTracker(config)`); avoids private-attr reach-through and keeps mypy --strict clean.
- **Profile-driven adjustments split across pipeline stages** — non-obvious: `suppress_rules` apply pre-syntactic-filter (Stage 1b) while `confidence_floor`/`severity_overrides` apply post-merge pre-`_compute_safe` (Stage 5b/5c), so the `safe` verdict respects profile adjustments (a floor-dropped HIGH does not flip safe=False).

RECONCILED: yes DRIFT: 3
