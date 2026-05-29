# Edge-Cases Review -- round 2

## Closure table
21 of 22 round 1 findings CLOSED. Edge-cases F-1 PARTIAL — `typing.get_type_hints()` note insufficient.

## Findings

### F-1: `typing.get_type_hints(PetasosConfig)` crashes due to TYPE_CHECKING-gated imports
**Severity:** P1
**Where:** spec.md:165
`Direction` and `Mapping` are imported under `if TYPE_CHECKING:` in config.py. `get_type_hints()` tries to resolve stringified annotations and raises `NameError`. Test must supply `localns` or use a different approach.
**Suggested fix:** Use `typing.get_type_hints(PetasosConfig, localns={'Direction': str, 'Mapping': dict})` or compare field types via string comparison `f.type == "bool"` on `dataclasses.fields()`.

### F-2: Test assertion for updated pipeline test is fragile (P4)
### F-3: JSON/YAML round-trip boundary (P3) — covered by Out of scope
### F-4: No test for `copy()` with non-default booleans (P3) — existing coverage sufficient

## Summary
P0: 0 | P1: 1 | P2: 0 | P3: 2 | P4: 1

STATUS: RED P0=0 P1=1 P2=0 P3=2 P4=1
