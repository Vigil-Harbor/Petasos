# Conventions Review — round 1

## Findings

### F-1 (P2, Pre-ship recommended: yes): `read_armed`/`write_armed` add mutable state + lock + file writes to the pure resolver `_paths.py`
`_paths.py:1-7` docstring: pure path *resolution*, stdlib only, never-raises, no module-level mutable state. The console subpackage has no precedent for a lock-guarded module cache (grep: only `_handlers` singletons in `plugin_api.py`). Adding `_ARMED_LOCK`, mutable `_ARMED_CACHE`, and a config-mutating `write_armed` stretches the module's single responsibility. Defensible (both gateway+dashboard already import `_paths`), but it is the spec's largest silent character change. Fix: either (a) add a sentence to Decision 4 acknowledging this is the first stateful/mutating code in the pure resolver and why; or (b) split into a sibling `petasos/console/_armed.py` importing `resolve_hermes_config_path` from `_paths`. (b) is cleaner long-term.

### F-2 (P2): `_post_tool_call` gate rationale misdescribes the code
`_post_tool_call` (`:511-516`) is only `if not _initialized: return` + a DEBUG log — it emits NO audit/alert. Audit/alert flow through the `on_audit=_handle_audit` pipeline callback fired inside `_guard.evaluate` during `_pre_tool_call`, which is already gated. So gating `_post_tool_call` only silences a debug line. Correct the rationale (or drop the gate); the "audit/alert silent" claim is wrong and the wiring test would pass for the wrong reason.

### F-3 (P2): new module-global cache has no test-reset convention in the named test home
`test_plugin_api_paths.py` resets resolver inputs per-test via monkeypatch but has no mechanism to clear a module-global cache (none exists today). Without a reset, a stale `_ARMED_CACHE` key leaks across tests (order-dependent passes). Test plan should mandate an autouse fixture resetting `_ARMED_CACHE = None` and assert `write_armed`'s same-process refresh against that baseline.

### F-4 (P3): deferring BUG-B (Decision 6) is consistent with repo norms — recorded for drift-check
Repo norm is to capture out-of-scope residuals as follow-up tickets (PET-90/PET-101/PET-108 precedent); the brief only mandates the BUG-A clobber-guard. Decision 4 makes the toggle correct regardless of BUG-B. No violation. Recommend filing the follow-up Plane ticket at ship time.

### F-5 (P3): BUG-A allowlist duplicates the "non-field petasos keys" knowledge — acceptable at N=2
`("enabled","host_id")` is asserted in `_persist_config` (explicit) and `write_armed` (implicit generic preserve). Correct and verified (`_BOOL_FIELDS` excludes both). At N=2 inline beats a shared constant; hoist `_NON_CONFIG_PETASOS_KEYS` only if a third site appears. No spec change.

### F-6 (P3): write_armed re-implements the blessed atomic-write idiom — intentional, not drift
tempfile→fdopen→fsync→os.replace→suppress(OSError) matches `_persist_config:73-88` (PET-81 pattern). The only divergence is the target dir (profile via `_paths` vs root via `_hermes_config_path` — the intentional Decision 4/6 point). Copy the proven block verbatim; do not "unify" the writers (would re-introduce BUG-B into the armed path).

### F-7 (P4): frontend honors PET-82/PET-89/ES5 — verified clean
`Pet.h`/`.textContent`, `.switch` reuse (no geometry change), `<button type="button">` + Enter/Space idiom (`renderConfig:931-938`), `Pet.asset("img/petasos-helmet.png")` (`:1146`), HelpTip→richText allow-list — all verified. Immediate-optimistic POST (vs renderConfig's buffered Apply) is an intentional, justified divergence for a master switch. No action.

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 3 | P4: 1

STATUS: GREEN
