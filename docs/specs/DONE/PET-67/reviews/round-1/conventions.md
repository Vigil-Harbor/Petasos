# Conventions Review — PET-67 Round 1

## Findings

### F-1: Adversarial test "After" code omits `@pytest.mark.asyncio` per existing file style
**Severity:** P4
Existing file uses explicit decorators on every async test despite `asyncio_mode = "auto"`. Functional but inconsistent.

### F-2: No note about PET-66 sibling ticket interaction
**Severity:** P3
PET-66 (SYN-02, whitespace injection) touches the same `_INJECTION_PATTERNS` list. PET-66 doesn't modify `system-prefix`, so merge order is independent, but the spec is silent on this.

### F-3: Spec creates new test vs brief's "extend existing" — unstated rationale
**Severity:** P3
Brief says "Unit test `test_system_prefix` covers at least one lowercase variant". Spec creates separate `test_system_prefix_case_insensitive`. Sound decision but rationale unstated.

### F-4: Red-team ledger target status not specified
**Severity:** P3
Spec says "updated with remediation commit" but doesn't specify target status value (e.g., `refuted` → `remediated`).

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 3 | P4: 1

STATUS: GREEN
