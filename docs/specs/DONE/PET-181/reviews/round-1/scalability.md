# Scalability Review — round 1

## Closure of round 1 findings
N/A — round 1

## Findings

### F-1: Exclusion first-sighting shares the 512 skip map with unbounded MCP not-string keys
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md Decision 7; spec § Plugin gate 3; `docs/deployment/reference_plugin/__init__.py:189-196` (`_MAX_INGEST_LOG_KEYS = 512`)
**Scale axis:** unbounded accumulation (shared first-sighting map) / operational observability at N
**Holds at target?:** Scanning still holds at ~73/81 + unbounded MCP names (O(1) exclusion, 8k clip, K=1 / P=8). Decision 7’s “once per excluded canon, falsifiable in a live deploy” does not: after invert, gate 2 `PETASOS_INGEST_NOT_STRING` fires for every ingesting non-string, including unknown MCP names (`__init__.py:2173-2182` plus Decision 7’s “that is correct”), so the 512-key drop-oldest map’s keyspace is no longer the ~81-tool census it was sized above.
**Why the spec misses it:** The spec reuses today’s `_note_ingest_skip` latch and does not mention `_MAX_INGEST_LOG_KEYS` in Files to change. Pre-invert, skip keys were census-sized (≪ 512), so “emits once” was process-lifetime in practice. Post-invert, 512 unique `(canon[:64], kind)` not-string keys evict the eight `kind="excluded"` latches; `test_ingest_excluded_emits_once` never fills the cap. The scan path is unaffected; the tripwire is.
**Suggested fix:** In Decision 7 and the gate-3 block: split `kind="excluded"` into a dedicated unevictable set (max 8) or pin those keys so drop-oldest cannot evict them; keep 512 as the bound for not-string/empty. Update the `_MAX_INGEST_LOG_KEYS` comment from “sits above the ~81-tool census” to “bound for unbounded MCP not-string first-sighting; exclusion latches are pinned/separate.” Record that “once” without that pin is until eviction.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 0 | P4: 0

STATUS: GREEN
