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
