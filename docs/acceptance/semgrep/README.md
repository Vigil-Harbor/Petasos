# Semgrep component evidence

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

The failed latency gate remains unresolved. No adjustment to the reviewed
thresholds is authorized or implied. The packaged qualification manifest remains
empty. Native Apple Silicon, Python 3.11, and hosted CI results are still required.
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
