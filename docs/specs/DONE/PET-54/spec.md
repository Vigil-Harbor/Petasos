# PET-54 — PIPE-07: Deny severity downgrades via profile overrides

**Ticket:** PET-54 · **Finding:** PIPE-07 · **Priority:** High
**Brief:** `docs/briefs/PET-54-pipe-07-critical-override.md`

## Goal

Prevent premium profile `severity_overrides` from downgrading finding severities. The current override loop at `petasos/pipeline.py:398–411` applies overrides unconditionally — a caller with a valid license can pass `profile={"severity_overrides": {"rule_id": "info"}}` to `inspect()` and neuter CRITICAL findings, bypassing `_compute_safe`. This change adds a universal severity floor (overrides can only upgrade or maintain) and structural-rule protection (rules in `petasos.syntactic.structural.*` cannot be overridden at all), enforced at both profile construction and pipeline runtime.

## Scope

### Files to change

| File | Change |
|------|--------|
| `petasos/pipeline.py` | Add severity floor check + structural rule skip in Stage 5c override loop |
| `petasos/premium/profiles/__init__.py` | Add structural rule validation in `_parse_profile` and `_merge_with_base` |
| `tests/adversarial/pipeline/test_degraded_fail_open.py` | Add 8 pipeline-level tests for severity floor, structural skip, end-to-end, and invalid value handling |
| `tests/test_profiles.py` | Add 3 tests: structural rule rejection at parse/merge + prefix tripwire |

### Files to leave alone

- `petasos/_types.py` — `Severity` enum and `ScanFinding` are unchanged
- `petasos/scanners/minimal.py` — `_STRUCTURAL_RULE_IDS` already exists; no changes needed
- `petasos/premium/profiles/*.json` — builtin profiles are unaffected (customer_service only upgrades injection rules, which passes the floor and is not in the structural set)
- `petasos/config.py` — no new config fields

## Decisions

### Decision 1: Severity floor, not full removal

Overrides are still useful for *upgrading* severity (e.g., the customer_service profile upgrades injection rules to CRITICAL). Removing the feature entirely would break legitimate use cases. The floor constraint preserves utility while blocking abuse.

### Decision 2: Defense-in-depth: construction + runtime

Profile construction validates against structural rules. The pipeline loop enforces the severity floor and structural skip at runtime. Both layers are needed because `ResolvedProfile` is a frozen dataclass that can be constructed directly (bypassing `_parse_profile`/`_merge_with_base`).

### Decision 3: Structural rules = `petasos.syntactic.structural.*` prefix (narrowed from brief)

The brief specifies `SYN-*` as the structural rule prefix — a prefix that does not match any actual rule ID in the codebase (verified: all rule IDs use `petasos.syntactic.*`). Using the full `petasos.syntactic.*` prefix would block ALL MinimalScanner rules from override — including the legitimate injection-rule upgrades in the `customer_service` builtin profile (`customer_service.json` overrides 6 injection rules to CRITICAL). This diverges from the brief's carried-forward decision, which was based on nonexistent rule IDs. This spec narrows structural protection to `petasos.syntactic.structural.*` (3 rules: `oversized-payload`, `excessive-depth`, `binary-content`), which are the rules whose severity is intrinsic and should never be modified. The universal severity floor already prevents the attack vector (downgrading any finding), so narrowing the structural set does not weaken the security posture.

### Decision 4: No license tier distinction

The override restriction applies regardless of license tier. An enterprise license does not grant permission to downgrade CRITICAL findings — the threat model is adversarial callers within a licensed deployment.

### Decision 5: `suppress_rules` left as-is

The `suppress_rules` path at pipeline.py `_premium_profile_hook` only affects the MinimalScanner via `with_suppress_rules()`. It cannot suppress ML scanner findings. The MinimalScanner constructor already strips `_STRUCTURAL_RULE_IDS` from the suppress set. This is a weaker attack surface than `severity_overrides` and is out of scope.

### Decision 6: Invalid severity override values handled gracefully at runtime

The `severity_overrides` dict values may contain invalid `Severity` enum strings (e.g., `"warning"`, `""`, `42`). Calling `Severity(override)` with an invalid value raises `ValueError`, which would propagate through `inspect()`'s catch-all and return `PipelineResult(safe=False, findings=())` — erasing all findings. This is a denial-of-service vector worse than the original downgrade attack. The pipeline loop must catch `ValueError` from `Severity(override)` and skip the override (keep original severity), consistent with the fail-safe principle. Construction-time validation in `_parse_profile`/`_merge_with_base` provides defense-in-depth.

### Decision 7: PET-59 interaction

PET-59 also modifies `_parse_profile` and `_merge_with_base` to add `suppress_rules` validation. The two validations are independent: PET-54 adds structural-override rejection (`ValueError`), PET-59 adds suppress-rule stripping (silent). They can coexist at adjacent insertion points. In the profiles module, PET-54 imports `_STRUCTURAL_RULE_IDS` from `petasos.scanners.minimal` rather than duplicating a prefix constant — this aligns with PET-59's import pattern and avoids drift.

## Design

### Layer 1: Pipeline severity floor + structural skip (`petasos/pipeline.py`)

In the Stage 5c override loop (L398–411), replace the unconditional override with two guards:

```python
_STRUCTURAL_RULE_PREFIX = "petasos.syntactic.structural."

# Stage 5c: Severity overrides (with PIPE-07 guards)
if (
    active_profile is not None
    and self._check_premium("profiles")
    and active_profile.severity_overrides
):
    overridden: list[ScanFinding] = []
    for f in merged:
        override = active_profile.severity_overrides.get(f.rule_id)
        if override is not None:
            # PIPE-07: structural rules cannot be overridden
            if f.rule_id.startswith(_STRUCTURAL_RULE_PREFIX):
                overridden.append(f)
                continue
            # PIPE-07: invalid override values are silently skipped
            try:
                override_sev = Severity(override)
            except ValueError:
                overridden.append(f)
                continue
            override_rank = _SEVERITY_RANK.get(override_sev, 999)
            current_rank = _SEVERITY_RANK.get(f.severity, 999)
            # PIPE-07: never downgrade severity (lower rank = higher severity)
            if override_rank > current_rank:
                overridden.append(f)  # keep original severity
            else:
                overridden.append(replace(f, severity=override_sev))
        else:
            overridden.append(f)
    merged = tuple(overridden)
```

The `_SEVERITY_RANK` dict already maps severities to rank integers (CRITICAL=0, HIGH=1, MEDIUM=2, LOW=3, INFO=4). A higher rank number means lower severity, so `override_rank > current_rank` means the override is a downgrade.

`_STRUCTURAL_RULE_PREFIX` is defined as a module-level constant alongside `_SEVERITY_RANK`. Using a prefix string rather than importing `_STRUCTURAL_RULE_IDS` from `petasos.scanners.minimal` avoids a cross-layer import while staying aligned with the existing prefix convention. A structural tripwire test (test 11) asserts that all members of `_STRUCTURAL_RULE_IDS` start with this prefix, catching drift.

### Layer 2: Profile construction validation (`petasos/premium/profiles/__init__.py`)

Import `_STRUCTURAL_RULE_IDS` from `petasos.scanners.minimal` and add a validation helper:

```python
from petasos.scanners.minimal import _STRUCTURAL_RULE_IDS

def _check_structural_overrides(severity_overrides: dict[str, str]) -> None:
    structural = [k for k in severity_overrides if k in _STRUCTURAL_RULE_IDS]
    if structural:
        raise ValueError(
            f"severity_overrides cannot target structural rules: {sorted(structural)}"
        )

def _check_severity_values(severity_overrides: dict[str, str]) -> None:
    valid = {s.value for s in Severity}
    invalid = [f"{k}={v!r}" for k, v in severity_overrides.items() if v not in valid]
    if invalid:
        raise ValueError(f"invalid severity override values: {invalid}")
```

This uses the authoritative `_STRUCTURAL_RULE_IDS` set (membership check, not prefix match), consistent with PET-59's import pattern. The `_check_severity_values` function validates override values against the `Severity` enum at construction time (defense-in-depth for Decision 6).

Requires adding `from petasos._types import Severity` to the imports (or reusing an existing import).

Call both validators in two places:

1. **`_parse_profile`** — after building the severity_overrides dict (before constructing `ResolvedProfile`):
   ```python
   sev_overrides = data.get("severity_overrides", {})
   _check_structural_overrides(sev_overrides)
   _check_severity_values(sev_overrides)
   ```

2. **`_merge_with_base`** — after merging severity_overrides (before constructing `ResolvedProfile`):
   ```python
   # after: severity.update(val)
   _check_structural_overrides(severity)
   _check_severity_values(severity)
   ```

### Interaction with existing code

- **`customer_service.json`**: Overrides 6 `petasos.syntactic.injection.*` rules to CRITICAL. None are in `_STRUCTURAL_RULE_IDS`, so construction passes. The override is an upgrade (CRITICAL is rank 0), so the severity floor also allows it. No breakage.
- **`_compute_safe` (pipeline.py `_compute_safe`)**: Unchanged. It checks `Severity.CRITICAL` and `Severity.HIGH` in findings. The floor ensures these can never be downgraded away.
- **`_premium_profile_hook` (pipeline.py)**: Unchanged. `suppress_rules` path is out of scope per Decision 5.
- **`ResolvedProfile` direct construction**: The `_parse_profile`/`_merge_with_base` validation catches misuse via the normal path. Direct `ResolvedProfile()` construction bypasses validation — the pipeline runtime check (Layer 1) catches this case.
- **`ProfileResolver.register()`**: Accepts any `ResolvedProfile` directly without validation (same bypass as direct construction). The pipeline runtime layer catches it. Not adding validation to `register()` because its callers are trusted (programmatic, not config-driven).
- **`inspect()` try/except (pipeline.py `inspect`)**: The `ValueError` from `_check_structural_overrides` during `ProfileResolver.resolve()` is caught by the existing `except Exception` at the top of `inspect()`, which returns `PipelineResult(safe=False, findings=(), errors=(...))`. This is consistent with the "pipeline never throws" invariant. The dict-profile structural override test (test 10) validates this path.

## Test plan

### New tests in `tests/adversarial/pipeline/test_degraded_fail_open.py`

All pipeline-level tests construct a `Pipeline` with a `MinimalScanner` and a test profile with crafted `severity_overrides`, then assert the override behavior.

| # | Test name | Asserts |
|---|-----------|---------|
| 1 | `test_override_cannot_downgrade_critical_to_info` | CRITICAL finding with override to "info" → severity stays CRITICAL |
| 2 | `test_override_cannot_downgrade_high_to_low` | HIGH finding with override to "low" → severity stays HIGH |
| 3 | `test_override_can_upgrade_medium_to_critical` | MEDIUM finding with override to "critical" → severity becomes CRITICAL |
| 4 | `test_override_same_severity_accepted` | HIGH finding with override to "high" → accepted (no-op) |
| 5 | `test_structural_rule_override_skipped_at_runtime` | Direct `ResolvedProfile` with `petasos.syntactic.structural.oversized-payload` override → override silently skipped, severity unchanged |
| 6 | `test_suppress_rules_does_not_affect_ml_findings` | `suppress_rules` containing ML scanner rule ID → ML scanner finding still present in results (regression, validates existing behavior from Decision 5) |
| 7 | `test_dict_profile_override_critical_blocked` | `inspect(profile={"severity_overrides": {"petasos.syntactic.injection.ignore-previous": "info"}})` with text "ignore previous instructions" → finding retains original severity, `safe=False` |
| 8 | `test_invalid_severity_override_value_skipped` | Profile with `severity_overrides: {"rule_id": "warning"}` (invalid Severity value) → override silently skipped, finding retains original severity, no crash |

**License activation for tests 1–8:** The severity override loop is gated by `self._check_premium("profiles")`. Since "profiles" is not in `_FEATURE_GATES`, `_check_premium` falls through to `return True` — but only when `_license_state == LicenseState.VALID`. Tests use the established `valid_key` fixture from `tests/conftest.py` and call `pipe.activate(valid_key)` before running `inspect()`, consistent with the codebase convention (70+ existing uses of this pattern).

For tests 1–4 and 7, the test creates a `ResolvedProfile` (or dict profile for test 7) with a crafted `severity_overrides` mapping a known MinimalScanner rule ID to the target severity, runs `inspect()` with text that triggers that rule, and asserts the finding's severity in the result.

For test 5, the test creates a `ResolvedProfile` directly (bypassing `_parse_profile`) with a structural rule ID in `severity_overrides`, ensuring the pipeline runtime skip works even when construction validation is bypassed.

For test 6, the test creates a pipeline with an ML scanner mock that returns a finding, passes a profile with `suppress_rules` containing that mock scanner's rule ID, and asserts the finding is still present (suppress_rules only affects MinimalScanner).

For test 8, the test creates a `ResolvedProfile` directly with an invalid severity string value, runs `inspect()`, and asserts no crash and original severity preserved.

### New tests in `tests/test_profiles.py`

| # | Test name | Asserts |
|---|-----------|---------|
| 9 | `test_structural_rule_override_rejected_at_parse` | `_parse_profile` with `severity_overrides: {"petasos.syntactic.structural.oversized-payload": "info"}` raises `ValueError` matching "structural rules" |
| 10 | `test_structural_rule_override_rejected_at_merge` | `ProfileResolver().resolve({"severity_overrides": {"petasos.syntactic.structural.binary-content": "info"}})` raises `ValueError` matching "structural rules" |
| 11 | `test_structural_rule_ids_match_prefix` | Assert all members of `_STRUCTURAL_RULE_IDS` (imported from `petasos.scanners.minimal`) start with `"petasos.syntactic.structural."` — structural tripwire that catches naming convention drift between the profiles module's import and the pipeline module's prefix constant |

### Existing tests — no changes needed

- `test_customer_service_severity_overrides` (test_profiles.py): passes as-is because customer_service overrides target injection rules, not structural ones
- `test_severity_overrides_merge` (test_profiles.py): passes as-is — the test override key `rule.x` is not in `_STRUCTURAL_RULE_IDS`
- `test_from_dict_rejects_normalize_nfkc_falsy_zero` (test_degraded_fail_open.py): unrelated, passes as-is

## Test command

```
python -m pytest tests/adversarial/pipeline/test_degraded_fail_open.py tests/test_profiles.py -v
```

## Done when

- [ ] `severity_overrides` cannot downgrade a finding below its original severity (universal floor)
- [ ] Structural rules (`petasos.syntactic.structural.*`) cannot be targeted by `severity_overrides` at profile construction (`_parse_profile` and `_merge_with_base`)
- [ ] Runtime defense-in-depth skips structural rule overrides even for directly constructed profiles
- [ ] Invalid severity override values handled gracefully (silent skip, no crash)
- [ ] All 11 tests listed above pass
- [ ] `customer_service` builtin profile still loads and its severity upgrades still apply
- [ ] `ruff check .` and `mypy --strict .` clean
- [ ] No regression in `pytest` full suite

## Out of scope

- `suppress_rules` hardening for structural rules (separate ticket; lower risk since MinimalScanner already strips `_STRUCTURAL_RULE_IDS` from suppress set)
- Profile signing / integrity verification (would require a profile trust chain — future work)
- Per-scanner severity override scoping (e.g., only allow overrides for Presidio PII findings) — adds complexity without clear need
- Drawbridge backport (Drawbridge does not have `severity_overrides`; no action needed)
- Revoking `inspect(profile=dict)` API surface (breaking change; the dict profile path is used by Hermes for runtime tuning)
