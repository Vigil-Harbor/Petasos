## Brief 6 · Guard + Profile Polish

**Plane items:** PET-37 (GUARD-04), PET-58 (PROF-03)
**Files touched:** `petasos/premium/guard.py`, `petasos/premium/profiles/__init__.py`, `tests/adversarial/guard/`, `tests/adversarial/profiles/`
**Priority:** medium (both)

### Findings

| ID | Severity | Attack | Current behavior | Remediation |
|----|----------|--------|------------------|-------------|
| GUARD-04 | medium | Exempt tool skips parameter scan entirely | Step 4 in `evaluate()` (line 118–125): if tool in `tool_exempt_list` → return `_EXEMPT_RESULT` immediately, never running `_scan_params()` | Add optional parameter scan for exempt tools: scan params but don't block on findings — return `allowed=True` with findings attached for audit trail |
| PROF-03 | medium | `register("general", evil_profile)` overwrites merge base | `register()` (line 254–255) stores any name in `_profiles` — including `"general"`, which is the merge base for all custom profiles | Forbid overwriting built-in profile names in `register()`: check against `_BUILTIN_NAMES` frozenset and raise `ValueError` |

### Approach

1. **GUARD-04:** In `evaluate()`, replace the early-return at Step 4 with:
   - Still skip *tier-based blocking* for exempt tools
   - Run `_scan_params()` if `config.exempt_param_scan` is True (default: True)
   - Return `GuardResult(allowed=True, findings=param_findings, reason="exempt-with-scan")`
   - This gives the audit trail visibility into what exempt tools are doing without blocking them

2. **PROF-03:** Add `_BUILTIN_NAMES = frozenset({"general", "customer_service", "code_generation", "research", "admin"})` to `profiles/__init__.py`. In `register()`, check `if name in _BUILTIN_NAMES: raise ValueError(f"Cannot overwrite built-in profile '{name}'")`.

### Decisions carried forward

- **GUARD-04 param scan default:** `exempt_param_scan=True` (scan by default) is the secure-by-default choice. Operators who want the old behavior (full bypass) can set it to `False`. The scan result is informational — it populates `GuardResult.findings` for audit but never flips `allowed` to `False` for exempt tools.
- **PROF-03 vs. resolver-level shadow:** An alternative is to let `register()` shadow built-ins in a per-resolver namespace. Decision: reject entirely — the built-in names are reserved. Custom profiles should use custom names and can inherit from `"general"` via `resolve({"base": "general", ...})`.

### Done when

- [ ] Exempt tool with dangerous parameters → `allowed=True` but `findings` populated
- [ ] `register("general", {...})` raises `ValueError`
- [ ] `register("my_custom", {...})` succeeds
- [ ] Audit events include findings from exempt tool param scans
- [ ] >= 8 tests (4 per finding)
- [ ] `mypy --strict` clean

### Out of scope

- Per-tool param scan policy (scan some exempt tools, not others) — future enhancement
- Profile versioning or migration
- GUARD-03 (already shipped in PET-36)
