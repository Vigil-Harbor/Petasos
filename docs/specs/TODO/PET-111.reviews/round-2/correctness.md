# Correctness Review — round 2

## Closure of round 1 findings
All round-1 findings CLOSED (verified against current spec + code):
- correctness/F-1 (P1) — armed gate moved to TOP of `_pre_tool_call`; three-way init handling preserved verbatim; only `_init_error == "disabled"` lines removed; no dead branch. CLOSED.
- correctness/F-2 (P2) — Decision 3 enumerates surviving `_init_error` readers (`:148`,`:362`). CLOSED.
- correctness/F-3,F-4 (P3) — anchors corrected; concrete enforce trigger named. CLOSED.
- edge/F-1 (P1) — TTL added to read_armed cache. CLOSED.
- edge/F-2 (P1) — set_armed returns (result, ok); POST 503 on failure; frontend reverts. CLOSED.
- edge/F-3,F-4,F-6,F-7,F-8,F-9 + conventions/F-1,F-2,F-3 — all CLOSED.
The literal `_init_error == "disabled"` has one reader (`:445`) + one writer (`:162`), both removed; truthiness readers (`:148`,`:362`,`:447`) untouched. No external/test reader asserts the sentinel.

## Findings

### F-1 (P2, Pre-ship recommended: yes): tripwire test is order-dependent — `_last_disarm_log` global has no reset seam
§ reference_plugin step 2 + test plan. The new module-global `_last_disarm_log` (rate-limit gate, `_DISARM_LOG_EVERY_S=30`) is set by the earlier `_pre_tool_call` disarm tests; the dedicated "logs once" tripwire test (spec test plan) then runs within 30 s, so `now - _last_disarm_log >= 30` is False → zero lines emitted → assertion fails. Identical class to the `_ARMED_CACHE` reset gap already fixed for `_armed.py`, but `_last_disarm_log` got no equivalent seam. Fix: add a `_reset_disarm_log()` seam (or `monkeypatch.setattr(ref, "_last_disarm_log", 0.0)`) and mandate it in the autouse reset fixture for `test_subagent_plugin_wiring.py`.

## Verified-correct
Option A / sentinel retirement clean; moved gate faithful to three-way init; `_armed.py` imports the pure never-raises resolver; BUG-A merge reads `existing` before overwrite; route 422/503 contract matches `{detail:[{field,message}]}` idiom; frontend anchors current; no symbol collisions; recent-merge anchors (PET-107/99/102) all match; Plane PET-111 matches brief.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 0 | P4: 0

STATUS: GREEN
