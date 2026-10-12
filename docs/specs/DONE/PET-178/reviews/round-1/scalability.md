# Scalability Review — round 1

## Closure of round 1 findings
N/A — round 1

## Findings

### F-1: Per-chunk decode cap multiplies PET-98's per-input DoS bound by ~18× at N=1e6
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:78, spec.md:135-139, spec.md:197, spec.md:294
**Scale axis:** resource-exhaustion / DoS bound that was O(1) per input becomes O(chunks)
**Holds at target?:** Still holds at 1,000,000 characters. 18 windows × `_DECODE_MAX_BLOBS=16` is 288 decode attempts (plus 18 ROT13 views) vs 16+1 on a one-shot scan. ~2.3 MB of extra injection-rescan work; order-of-hundreds of ms, not a miss of `_result_scan_timeout`. The architecture reaches N. The bound silently moved.
**Why the spec misses it:** `MinimalScanner._check_encoded_payloads` (`petasos/scanners/minimal.py:419-420, 953-957`) caps blob attempts **per `scan()` call**, not per result. Decision 16 chunks the ceiling into 18 windows of 65,536 so a one-shot 1e6 ASCII payload does not trip `max_payload_bytes=524_288`. Helper step 5 then `await scanner.scan(chunk)` once per origin. That is the right coverage structure (and it improves ROT13 coverage, which is only the first 8,192 chars of each input). It also multiplies the PET-98 DoS cap by `ceil((1e6-8192)/57344)=18`. CHANGELOG residuals name hex-blob splits at a cut, the shared 30 s breaker, and `weight_cap` not stepping on chunk findings — not this 18× decode budget.
**Suggested fix:** Name it next to the hex-split residual: at the ceiling the decode-rescan budget is per chunk, so ≤18×16 blob attempts plus 18 ROT13 views, not 16+1 per result. Optionally keep a helper-level remaining-blob counter so the PET-98 cap stays per result; that is not required to hit N.

### F-2: Ingest timeout clock includes the K=1 lock wait, so 8 concurrent 1e6 helper runs share one budget
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:103-105, spec.md:207-218, spec.md:280-282
**Scale axis:** fan-out / backpressure; operational latency under the 8-wide dimension
**Holds at target?:** Serial 1e6 holds. PET-170's ~53.9 ms MinimalScanner / 100 KB extrapolates to ~0.6 s for 1.14e6 overlapped characters, well under the default 15 s (`scanner_timeout` 10 + 5, cap 65). 8-wide **`inspect()`** also holds: Decision 10 keeps it as a gather of eight `HEAD_CHARS` calls, cheaper than today's 8 k window. What is unstated is the product: 8 concurrent **helper** runs serialize on K=1 (brief Q11 A), and `_run_ingest_async(..., timeout=budget)` wraps `_ingest_one`, which acquires the ingest `asyncio.Lock` **before** `scan_ingestion_result`. Queue wait counts against the same budget as the scan. Base-install 8×~0.6 s ≈ 4.8 s still fits. ML head (~0.7–1.1 s from CLAUDE.md) plus sweep, times 8, is ~12–17 s — inside 15 s on the PET-170 box, over it on the slower bench box. Later slots then take `scan_unavailable` even though each individual 1e6 sweep would have succeeded. P=80 stays a residual; this is 8-wide, which the brief did declare.
**Why the spec misses it:** Decision 11 and the helper-8-wide benchmark correctly refuse to treat K=1 serial as equal to 8-wide `inspect()`. Line 218 only claims “a 1e6 syntactic sweep is expected well under that on a base install.” It does not say whether `budget` starts at submit or after the lock, so an implementer copying `_run_async` will time the wait. That is a coverage hole under concurrent 1e6 ingestions (`ingest_unscanned`), not a fail-open of `_pre_tool_call`.
**Suggested fix:** Start the timeout after the ingest lock is acquired (lock wait is unbounded except by the caller's patience, scan work keeps the existing budget), **or** record in Decision 11 / the 8-wide helper test that wall time is the sum of heads+sweeps and that later slots may `scan_unavailable` under ML at 8×1e6. Do not treat that as a P=80 problem.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 0 | P4: 0

STATUS: GREEN
