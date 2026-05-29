# Edge-Cases Review — Round 1

### F-1 (P4): Line references verified accurate. No issue.
### F-2 (P3): Thread safety of empty-components check — safe under CPython GIL, `self._components` populated under lock before `self._loaded` is set.
### F-3 (P2): Empty-components path conflation risk — L161 is only reachable when `_ensure_loaded()` succeeded AND all enable flags are False. No conflation today; suggest a comment documenting this invariant.
### F-4 (P2): Constructor warning fires before `_ensure_loaded()` confirms package is importable — misleading log when package isn't installed. Suggest deferring warning to inside `_ensure_loaded()` when load succeeds but components are empty.
### F-5 (P3): No pipeline-level integration test for the new error signal. Suggest adding a 5-line test with `Pipeline([LlamaFirewallScanner(all disabled)])` under `degraded` fail-mode.
### F-6 (P4): Empty string input irrelevant on error path — clean.
### F-7 (P4): `any([list])` vs generator — possible lint issue, suggest simplifying to `or` expression.
### F-8 (P3): Test 3 does not specify mock injection context — specify that all new tests should use `_injected_mock()` in TestUnit class.

P0: 0 | P1: 0 | P2: 2 | P3: 3 | P4: 3

STATUS: GREEN
