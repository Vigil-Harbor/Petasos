# PET-65 Conventions Review -- Round 1

## Findings

### F-1: Test command uses Python 3.10 interpreter; project requires >= 3.11 (P1)
`C:\python310\python.exe` path name suggests 3.10. pyproject.toml requires >=3.11. CLAUDE.md says Python 3.11+. PET-31 noted this pitfall.

### F-2: mypy --strict scoped to single file, contradicts brief and CI convention (P2)
Brief says `mypy --strict .`, CI runs `mypy --strict .`, 14+ peer specs use project-wide scope. Spec narrows to single file without rationale.

### F-3: ruff format --check missing from test command (P2)
CI runs both `ruff check .` and `ruff format --check .`. Recent peer specs include format checking. Spec omits it.

### F-4: Spec narrows Done When mypy scope vs brief without acknowledgment (P2)
Brief line 146: `mypy --strict .`. Spec: `mypy --strict petasos/scanners/__init__.py`. Silent deviation.

### F-5: Spec adds test 4 (submodule rejection) not in brief (P3)
Replaces brief's test_transitive_dep_failure_reraises. Well-motivated by Decision 3. Category (c) addition.

### F-6: Spec Done When adds submodule criterion not in brief (P3)
New criterion flows from Decision 3. Legitimate tightening, category (c).

## Summary
P0: 0 | P1: 1 | P2: 3 | P3: 2 | P4: 0

STATUS: RED P0=0 P1=1 P2=3 P3=2 P4=0
