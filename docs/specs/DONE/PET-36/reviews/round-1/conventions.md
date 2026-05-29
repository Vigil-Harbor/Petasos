# Conventions Review — round 1

## Findings

### F-1: Test-command interpreter `py -3.13` matches no sibling spec — P2
Recent specs pin via absolute path or bare python: PET-8 `python -m pytest`, PET-9 `...Python313\python.exe -m pytest`, PET-10 `C:\python310\python.exe -m pytest`, PET-11 `python -m pytest`. None use the `py -3.13` launcher. CLAUDE.md uses bare `pytest`. Non-blocking (command runs if `py -3.13` resolves to a deps-bearing env) but forks the pinning convention.
**Fix:** use PET-9 absolute-path form or bare `python -m pytest`; if `py -3.13` is the new standard that's a cross-spec decision, not PET-36-local. (Reviewer note: bare `python` on this host has been observed as 3.10, which fails `requires-python>=3.11` — an explicit pin is warranted; just align the *form*.)

### F-2: Test command omits `ruff format --check` that PET-9/PET-10 include — P3
PET-36 chains `ruff check && mypy`; PET-9 also chains `ruff format --check`. CLAUDE.md lists `ruff format .` as first-class. New multi-line code blocks could drift formatting.
**Fix:** add `&& ruff format --check .`; optionally add format to Done-when.

### F-3: D7 case-insensitive collision check is stricter than the brief — P3 (validation)
Brief snippet is raw `set(alias_map.values()) & exempt_set`; spec strengthens to lowercased. Correct, well-reasoned (matches repo lowercase discipline), and labelled as a "correctness nuance" (class-c addition-with-rationale, not silent). Surfaced for the drift checklist only.

### F-4: D6 structural-invariant-as-test correctly overrides brief's import-time assert — P3 (validation)
A module-load assert would couple `import guard` to ProfileResolver JSON I/O (crash-on-import). PET-8 spec explicitly reasoned construction-validation is fine but "never throws" applies to inspect(), not construction/import. The test gives the same guarantee without the coupling. Sound deviation.

## Passed (no findings)
- ValueError-at-construction is the established pattern (existing raises at profiles/__init__.py:76,98,105,112,123,130,136,143,153); "never throws" applies to inspect(), not construction (confirmed PET-8 spec). Error-message f-string + sorted() + subject-prefix style matches.
- Flat test layout (D5) confirmed real; no `tests/unit/premium/` tree. New tests fit existing `_profile`/`_guard` helper + direct-`ResolvedProfile` style.
- Frozen-exports respected (no built-in JSON edited, DEFAULT_TOOL_ALIASES unchanged, alias_map still MappingProxyType, fallback returns pre-alias without mutation).
- OSS/premium split respected (all changes under petasos/premium/).
- Defense-in-depth two-gate justified, not over-engineering: ResolvedProfile is constructed directly by the existing test corpus (test_tool_smuggling.py:41, test_guard.py:37), so the runtime backstop is real, not hypothetical.
- No new registry/abstraction (dangerous-tools registry explicitly out of scope).
- No wiki decision contradicts; `2026-04-29-tool-namespacing-double-underscore.md` governs the namespace regex PET-36 doesn't touch.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 3 | P4: 0

STATUS: GREEN
