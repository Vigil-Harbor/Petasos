# Conventions Review -- round 2

## Closure of round 1 findings
All R1 findings CLOSED. Key fixes: test #13 noted as "append to existing", `_MAX_PARAM_TEXT_LEN` module-level placement explicit, `mypy --strict` added, D4 reframed for independent justification.

## Findings

### F-1: Test command scoped ruff/mypy to two files vs Done When whole-repo (P2)
Test command used file-specific paths for ruff/mypy but Done When says `.`. Fixed mid-round — test command now uses `.` matching Done When and CI.

### F-2: `_safe_json.py` not in filemap.md (P3, informational)
New file not noted for filemap update. Handled automatically by `/wiki-after-merge` skill post-merge. Consistent with other specs.

### F-3: Brief `_MAX_PARAM_TEXT_BYTES` → spec `_MAX_PARAM_TEXT_LEN` override (P4)
Silent but obviously correct rename driven by review findings. No formal decision entry needed.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 1 | P4: 1

STATUS: GREEN
