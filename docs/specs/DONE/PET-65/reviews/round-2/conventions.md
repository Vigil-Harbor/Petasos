# PET-65 Conventions Review -- Round 2

## Closure of round 1 findings
All round 1 findings CLOSED:
- F-1 (P1): Interpreter fixed to `py -3.13`
- F-2 (P2): mypy --strict now project-wide
- F-3 (P2): ruff format --check added
- F-4 (P2): Done When mypy scope matches brief
- F-5 (P3): Test substitution acknowledged in spec
- F-6 (P3): Submodule criterion acknowledged as Decision 3

## Findings

### F-1: Bare ruff/mypy invocation vs py -3.13 -m prefix (P4)
PET-31/PET-36 use `py -3.13 -m ruff`. PET-65 uses bare `ruff`. CI also uses bare. Nit.

### F-2: Spec Done When adds ruff format --check not in brief (P3)
Category (c) addition — aligns with CI gate.

### F-3: Spec expands from 8 to 11 tests without summary note (P3)
Category (c) — driven by round 1 edge-case findings. All additions defensible.

### F-4: First DEBUG-level log in codebase (P4)
Precedent-setting but authorized by brief Decision 1.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 2 | P4: 2

STATUS: GREEN
