# Conventions Review — round 3

## Closure of round 2 findings
All CLOSED: conventions F-1 (Decision 1 cites PET-23/PET-75/PET-107 — verified accurate to each decision's axis), F-2 (`_armed.py` cold-path import note; matches `_persist_config` server.py:51-54), F-3 (alias dropped, module-top `import time` directed, `_disarm_log_lock` added). Cross-lens correctness F-1, edge F-1/F-2/F-3/F-4/F-5 CLOSED. No `[tool.ruff]` lint config → PLC0415 (import-outside-top-level) not enabled, so function-local imports raise no lint concern (the existing `_persist_config` confirms the idiom is blessed). `tests/test_console_armed.py` follows the `test_console_*` convention.

## Findings

### F-1 (P3): Decision step 2 asserts a `time` import in `reference_plugin` that does not exist
§ reference_plugin step 2. "the PET-107 lineage/spawn-budget code already imports `time` — reuse it" is false: grep of `reference_plugin/__init__.py` for `time` = zero matches; module-top imports are `asyncio, base64, logging, os, threading, uuid` only. The *directive* (module-top `import time`) is correct and the net code outcome is right, so P3 — but the justification is a false grounding claim (violates the "verify load-bearing claims" convention) and would seed a wrong statement into the comprehension page. Fix: change the parenthetical to "Add a module-top `import time` (the file imports no `time` today — confirmed; place it with the stdlib block at `:17-23`)."

## Silent-additions check
No new (d) silent additions. All round-3 edits are (c) spec-level-with-rationale closures of round-2 findings or (a) brief-authorized. Scope deferrals (BUG-B, multi-tab SSE) unchanged. Decision 1's "new operator-kill-switch axis" framing is a legitimate reconciliation leaving the three prior floor decisions intact.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 1 | P4: 0

STATUS: GREEN
