# Semgrep component evidence

## 64 KiB maximum (protocol v3): counting run at fb65503 passed

Hosted run
[42439292090](https://github.com/Vigil-Harbor/Petasos/actions/runs/42439292090)
is the single corrected measurement fixed by the rerun rule below. It measured
merge revision `f833b5e99de6eb0dee2bdedc201ff639900df7b2` for branch head
`fb65503`, with workload `eight_outstanding_three_profiles_16k_64k_v3`, manifest
`62d44848...945e` and criteria `S7-2026-11-07-v2`. Summaries are retained in
`hosted-mac-fb65503.json` and `hosted-win-fb65503.json`.

**Every v3 component gate passed on both platforms in this run: 17 of 17 rows,
zero errors, empty `gate_failures`.** `qualified` stays `false` because the
qualification manifest is still empty; that is a separate release gate.

| Row (limit) | macOS 15 | Windows Server 2025 |
|---|---|---|
| Single 16 KiB mean / p95 / p99 (1.0 / 1.2 / 1.4 s) | 0.575 / 0.693 / 0.748 | 0.778 / 0.812 / 0.966 |
| 64 KiB repeated mean / p95 / p99 (1.8 / 2.0 / 2.3 s) | 0.924 / 1.165 / 1.248 | 1.264 / 1.410 / 1.740 |
| 64 KiB distinct mean / p95 / p99 (1.8 / 2.0 / 2.3 s) | 0.866 / 1.074 / 1.269 | 1.218 / 1.378 / 1.397 |
| Eight-wide 16 KiB, worst p95 of six (5.0 s) | 3.085 | 4.705 |
| Eight-wide 64 KiB, worst p95 of six (7.5 s) | 3.954 | 5.931 |
| Eight-wide 64 KiB, worst max of six (8.0 s) | 4.218 | 6.111 |
| Replacements p95 (7.5 s) | 2.842 | 3.595 |
| Preflight 1M p95 (0.050 s) | 0.022 | 0.012 |

Hosts: macOS Apple M1 (Virtual), 3 cores, image `20261104.0514.1`; Windows AMD
Family 25 Model 17, 2 physical cores, image `20261103.298.1`; Python 3.14.10 on
both. The Windows host looked like the `5221a7c` reference, not the slow
`51acf8e` host: native suite 86.72 s, preflight mean 0.011 s, single 16 KiB cold
probe 0.545 s.

Margins worth watching. These are observations, not failures:

- Windows eight-wide 16 KiB shared-owner 8/0/0 had p95 4.705 s against 5.0 s,
  p99 5.976 s and max 6.993 s. That is about 6% headroom on the binding 16 KiB
  row. The 16 KiB eight-wide gate has no per-request maximum.
- Windows 64 KiB repeated had one 4.343 s serial outlier. Its p99 of 1.740 s is
  within 2.3 s.

Other jobs in the same run: `scanner-tests (windows-2025, 3.11)` failed one
functional test, `test_sibling_errors_and_discard_time_preserved`. It measured a
20 ms sleep as 0.015 s because Python 3.11 on Windows backs `time.monotonic()`
with a 15.625 ms tick (3.13+ use a fine-grained clock). That lane runs no
benchmark. Commit `7ce5525` allows for the clock's reported resolution. macOS 3.11
passed.

Runs that do not count: 42438233233 (`e86b922`) and 42439132916 (`ba84582`) were
started by documentation pushes. Pull-request path filters evaluate the whole PR
diff, so every push starts this lane. Both were cancelled without reading their
results. The run started by the push that records this section also does not
count.

## 64 KiB maximum (protocol v3): first hosted attempt at 51acf8e

On November 7, 2026 the operator lowered the supported maximum source to 64 KiB
([protocol v3](protocol-v3.md)); latency limits are unchanged. Hosted run
[42436053501](https://github.com/Vigil-Harbor/Petasos/actions/runs/42436053501)
measured merge revision `7a447f21be58b9cee15832a4564887d14a928740` for branch head
`51acf8e`. Summaries (per-sample data omitted for size) are retained in
`hosted-mac-51acf8e.json` and `hosted-win-51acf8e.json`.

- **macOS 15 / Python 3.14 (Apple M1 virtual, 3 cores): every component gate
  passed.** 64 KiB serial repeated/distinct mean 1.128/1.044 s. The six 64 KiB
  eight-wide cases had p95 4.77-5.09 s, max 5.77 s and zero errors.
- **Windows Server 2025 / Python 3.14 (AMD Family 25 Model 17, 2 physical cores):
  FAILED.** All seven 64 KiB rows passed: serial repeated/distinct mean
  1.510/1.478 s, and the six eight-wide cases had p95 6.89-7.05 s, max 7.38 s and
  zero errors. Two unchanged 16 KiB rows failed: serial single mean 1.022 s
  (limit 1.0 s) and eight-wide 16 KiB shared-owner 4/2/2 p95 5.561 s (limit 5.0 s).

An independent review (`.claude/reviews/PET-254-S7-v3-review-1.md`, local)
judged a slower Windows host **plausible and strongly supported, but not
verified**. `51acf8e` changes only the source-byte cap, which neither a single
16 KiB target nor preflight reaches. Against run 42404464485 (`5221a7c`, same base
`39b4cb1`, same hardware label, image `20261103.298.1`, Python and engine), the
native test suite on the same VM before the benchmark slowed from 81.66 s to
109.37 s (median 1.33x across 278 common tests). Comparable benchmark cases
slowed by a similar factor: single 16 KiB mean 0.785 to 1.022 s, cold probe 0.544
to 0.697 s, engine-free preflight mean 0.0112 to 0.0145 s with non-overlapping
distributions. The macOS control was flat (suite 62.15 to 60.83 s). The 4/2/2
p95 failure also needed a short extra episode: burst maxima stepped up at burst 7,
and control-loop lag reached 0.427 s against at most 0.114 s in most cases. Not
every summary stage duration slowed; those pool different workload mixes.

The 64 KiB passes above were measured on the same slower host. They support the
64 KiB capacity estimate but are not a qualifying result by themselves.
Qualification needs one complete v3 run in which every row passes. The Windows
failure stands until the operator accepts a verified infrastructure cause or a
reviewed repair, and a rerun alone does not erase it. The qualification manifest
remains empty.

### Operator decision and rerun rule (November 7, 2026)

Fixed before the rerun:

1. The operator accepts the slower Windows host as the cause of the `51acf8e`
   Windows failure, on the evidence above. The failed attempt stays on record.
2. Exactly one corrected measurement: the next push that changes the native lane
   (the source-limit boundary tests from the review) runs the complete v3
   benchmark on both Python 3.14 platforms.
3. Only that run counts. Qualification of the v3 component gates needs every row
   to pass on both platforms in that same run. Rows from `51acf8e` are not combined
   with it.
4. If any row fails on either platform, that failure stands. There is no further
   retry. The result goes back to the operator as a gate-margin decision (the
   single 16 KiB mean has about 21% baseline headroom on this label).
5. For interpretation only, not as a filter: the `5221a7c` Windows reference is a
   native suite of 81.66 s, preflight mean 0.0112 s and single 16 KiB cold probe
   0.544 s. The run records its own figures.

## Approved S7 v2 amendment (superseded by v3 for new measurements)

On November 7, 2026 the operator approved the reviewed
[v2 measurement protocol](protocol-v2.md): maximum-source serial limits are
1.8 s mean / 2.0 s p95 / 2.3 s p99, plus an independent eight-wide maximum-source
gate at 7.5 s p95, every request ≤8 s, zero errors. Other latency limits,
coverage and cleanup bounds remain unchanged. Loaded samples increase to 104
per case, with pinned fixtures, exact findings/coverage checks, resource
telemetry and preserved partial failures. Historical measurements below retain
their original criteria and failure status. They do not qualify the new workload.

## Completed hosted measurements at 5a13965

The November 7, 2026 hosted run
[42369954500](https://github.com/Vigil-Harbor/Petasos/actions/runs/42369954500)
measured the PR merge revision `e59f4d14b30a32f84e445c9b635943579c3ff042`
for branch head `5a13965`. The unchanged artifact data is retained in
`hosted-mac-5a13965.json` and `hosted-win-5a13965.json`.

Both Python 3.14 native suites passed: Mac 242 passed with two Windows-only
skips; Windows 243 passed with one POSIX-only skip. The Mac run executed the
native zombie-group cleanup test and all four additional signal transitions.
Both benchmarks completed, closed their owners, and recorded no stage errors.
Single 16 KiB scans, all six eight-wide scheduling distributions and cancellation
replacements passed their gates. The 16-candidate/128 KiB workload failed all
three serial latency limits on both platforms. Windows also failed the
million-character preflight gate; Mac passed it.

These are **failed component qualifications**. Package S permits declared hosted
measurement hardware, so the Mac runner's three cores and 7 GiB RAM do not waive
its failed gates. Q's real-host hardware requirements and eight-hour soaks are
separate. The successful Windows cleanup in this run does not resolve the
earlier intermittent root-removal failure. At that run's revision no thresholds
or cleanup budgets had changed. The later amendment above changes only the
specified acceptance protocol; the qualification manifest remains empty.

## Earlier local evidence

These are exploratory Windows x64 / Python 3.14 measurements of the PET-254
package-S implementation candidate before its first commit. They are not a
qualification certificate or evidence of a Hermes gateway run. The engine and
rules digests, hardware and workload sizes are recorded in the JSON files.

- `windows-exploratory.json`: initial run, overlapping other regression tests.
  Single-request p95/p99 and maximum-source p99 missed the reviewed limits.
- `windows-isolated.json`: repeated without concurrent test suites. Single 16 KiB
  p99 was 3.162 seconds against a 1.4-second limit. Its mean and p95 passed;
  the 16-target / 128 KiB case passed all three thresholds. All three eight-wide
  distributions and cancellation replacements passed their p95 limits. Close
  completed successfully. This run predates the final prepared-input fingerprint
  check and is diagnostic evidence, not an exact committed-revision performance proof.

This earlier failed latency gate was not waived. The later approved amendment
requires new measurements; it does not reclassify these results. The packaged
qualification manifest remains empty. Native Apple Silicon, Python 3.11, and
hosted CI evidence was still outstanding at this historical revision.
The benchmark script exits nonzero on a missed gate and saves its measurements;
the native workflow runs it on both Python 3.14 platform cells.

Functional evidence collected during implementation: 3,495 base-suite passes
(172 optional skips and one expected failure), 165 final required-engine Windows
passes with no skips, and 388 JavaScript passes. The final focused base run passed
249 tests with three real-engine tests skipped; strict typing passed 218 source
files, Ruff passed, and the built wheel contains all rule assets. Synthetic process helpers establish lifecycle
behavior only. Detector evidence uses the pinned real engine and a separate
72-case held-out corpus (12 positive and 12 negative cases per language).

Remaining release work includes native resource/performance gates, the supported
Hermes cleanup callback, durable reporting, host warning delivery and both
8-hour real-host soaks. Package S does not enable the backend in Hermes.

## First code-review repairs (not qualification)

The repair candidate forces real parsing in every selected grammar, retains
findings across partial parses, projects indented fragments and earlier JSON
leaves, and admits work before allocating projection maps. It also consumes the
qualification manifest and pins both downloaded engine wheels and engine bytes.
The measurement script now records revision/environment identity, uses dense code,
exercises three owners, and saves stage timings and partial failed measurements.

Windows Python 3.14 verification during this repair pass:

- The broad regression run passed 3,514 tests, with 186 optional skips and one
  expected failure. This preceded the final additional regression fixtures.
- The subsequent required-engine run passed 198 tests and failed the native
  long-running-child cancellation test: cleanup exceeded its two-second budget.
  Five isolated repeats passed, but a separate 60-cancellation diagnostic
  reproduced one cleanup failure. Its original owned process handle signaled
  before the deadline; complete cleanup confirmation arrived later. The cause
  remains unresolved. This is a failed stability gate, not an accepted flake.
- Indented patch fragments across all four affected Python rule families, deep
  JSON with earlier code, Python line-boundary postfilter regressions, and the
  qualification fallback are covered by the passing required-engine cases.

The two-second cleanup budget and all latency limits remain unchanged. These
results do not qualify S, and the runtime continues to retain ownership/capacity
when cleanup cannot be confirmed. Native Apple Silicon, Python 3.11, hosted CI,
and real Presidio/PromptGuard/Semgrep composition remain unverified. The latter
now has an opt-in test requiring the actual backends and cached model assets.

## Second code-review repairs

Code-free JSON now bypasses engine queue admission after a bounded escaped-content
preflight. Native lifecycle work uses the existing two owned workers so a slow
CreateProcess call does not block the shared control loop. Windows launches use
detached processes with explicit pipes; the Job Object still owns each process
before it resumes. Native tests prove the simple child has no console-host member.
A worker timeout retains capacity and cleanup failures survive cancellation.

These changes do not yet establish stability: an intermediate required-engine run
passed 203 tests and failed the descendant-holding-pipes cleanup gate. Earlier
runs also recorded a probe prerequisite failure and an output-limit helper timeout.
Twenty subsequent descendant diagnostics completed, but do not erase that failure.
The runtime now retains bounded, source-free handle/accounting snapshots on failed
cleanup. The two-second bound and all latency thresholds remain unchanged.

## Third code-review repairs

Streaming preflight now carries whitespace and incomplete escapes across chunk
boundaries; the padded-call bypass has raw, JSON, mixed-leaf and double-escaped
regressions through the real engine. Native worker and supervisor share the
reported cleanup deadline, and findings survive a later language's native failure.
Constructor-watchdog and native-cleanup phases are documented separately; owner
and process-close absolute deadlines remain unchanged. No qualification is implied.

The precommit Windows/Python3.14 native gate passed224 tests, including the pinned
engine's Job-membership check (no descendants observed). Lifecycle helpers now
explicitly keep any intentionally-created console descendant hidden; stream tests
use the base interpreter rather than an unrelated virtual-environment launcher.
Historical cleanup and latency failures above remain evidence until the revised
commit completes its required gates.
